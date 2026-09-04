"""Tests for bounds validation and the human-gated settlement flow."""
import pytest

from app.audit import AuditLogger, EventType
from app.models import BundleOffer, BundleStatus
from app.payments import (
    BoundsViolation,
    ConfirmationError,
    MockPaymentClient,
    PaymentService,
    SettlementBounds,
    SettlementStatus,
    validate_bounds,
)

# Laptop Rs.80000 + bag Rs.4000; 10% off; A concedes 8000 -> A gets 72000,
# B gets 4000; customer pays 76000.
OFFER = BundleOffer(
    bundle_id="bnd_test",
    product_a_id="pa", product_b_id="pb",
    merchant_a_id="ma", merchant_b_id="mb",
    affinity_score=0.5,
    original_total_inr=84000, discount_pct=10.0,
    merchant_a_discount_pct=10.5, merchant_b_discount_pct=0.0,
    bundle_price_inr=75600,
    merchant_a_amount_inr=71600, merchant_b_amount_inr=4000,
    rationale="test", status=BundleStatus.AGREED,
)
BOUNDS = SettlementBounds(
    price_a_inr=80000, price_b_inr=4000,
    min_margin_a_pct=88, min_margin_b_pct=80,
)
ACCOUNTS = {"ma": "acc_testA", "mb": "acc_testB"}
CID = "sess_pay_test"


def _service(ttl=300, cap=200000):
    return PaymentService(
        MockPaymentClient(), AuditLogger(":memory:"),
        cap_inr=cap, confirmation_ttl_seconds=ttl,
    )


# -- bounds -----------------------------------------------------------------

def test_valid_offer_passes_bounds():
    assert validate_bounds(OFFER, BOUNDS, cap_inr=200000) == []


def test_bounds_flag_margin_breach():
    # A must retain 88% of 80000 = 70400; give A only 60000 -> breach.
    bad = OFFER.model_copy(update={
        "merchant_a_amount_inr": 60000, "merchant_b_amount_inr": 15600,
    })
    violations = validate_bounds(bad, BOUNDS, cap_inr=200000)
    assert any("merchant A" in v for v in violations)


def test_bounds_flag_cap_exceeded():
    violations = validate_bounds(OFFER, BOUNDS, cap_inr=50000)
    assert any("cap" in v for v in violations)


def test_create_order_rejects_bad_bounds_without_calling_api():
    svc = _service(cap=50000)  # cap below bundle price -> must reject
    client = svc._client
    with pytest.raises(BoundsViolation):
        svc.create_bundle_order(OFFER, BOUNDS, ACCOUNTS, CID)
    assert client.orders == []          # no API call happened
    story = svc._audit.get_story(CID)
    assert story[-1].event_type is EventType.FAILURE
    assert story[-1].decision["api_called"] is False


# -- human gate -------------------------------------------------------------

def test_transfers_created_on_hold_and_not_settled():
    svc = _service()
    pending = svc.create_bundle_order(OFFER, BOUNDS, ACCOUNTS, CID)
    order = svc._client.orders[0]
    assert all(t["on_hold"] for t in order["transfers"])   # money held
    assert svc._client.released == []                      # nothing settled yet
    assert pending.status is SettlementStatus.PENDING


def test_wrong_otp_does_not_settle():
    svc = _service()
    pending = svc.create_bundle_order(OFFER, BOUNDS, ACCOUNTS, CID)
    with pytest.raises(ConfirmationError):
        svc.confirm_and_settle(pending.order_id, otp="000000")
    assert svc._client.released == []                      # still held
    assert svc.get_pending(pending.order_id).status is SettlementStatus.PENDING


def test_correct_otp_settles_and_releases_transfers():
    svc = _service()
    pending = svc.create_bundle_order(OFFER, BOUNDS, ACCOUNTS, CID)
    settled = svc.confirm_and_settle(pending.order_id, otp=pending.otp)
    assert settled.status is SettlementStatus.SETTLED
    assert set(svc._client.released) == set(pending.transfer_ids)
    types = [e.event_type for e in svc._audit.get_story(CID)]
    assert EventType.PAYMENT_INITIATED in types
    assert EventType.CUSTOMER_CONFIRMATION in types
    assert EventType.SPLIT_EXECUTED in types


def test_expired_offer_cannot_settle():
    svc = _service(ttl=0)  # expires immediately
    pending = svc.create_bundle_order(OFFER, BOUNDS, ACCOUNTS, CID)
    with pytest.raises(ConfirmationError):
        svc.confirm_and_settle(pending.order_id, otp=pending.otp)
    assert svc._client.released == []
    assert svc.get_pending(pending.order_id).status is SettlementStatus.EXPIRED


def test_expire_stale_logs_rollback():
    svc = _service(ttl=0)
    svc.create_bundle_order(OFFER, BOUNDS, ACCOUNTS, CID)
    expired = svc.expire_stale()
    assert len(expired) == 1
    assert svc._audit.get_story(CID)[-1].event_type is EventType.ROLLBACK
