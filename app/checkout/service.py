"""CheckoutService — the end-to-end orchestration behind the API.

initiate(): match -> negotiate -> validate bounds -> produce an offer + OTP.
            Nothing is reserved or charged yet. Returns the offer (or no-offer).
confirm():  validate the OTP human-gate, then run the saga to reserve inventory,
            capture payment, and execute the split — with graceful compensation.

Everything shares one correlation_id so GET /audit/{id} tells the full story.
"""
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.agents import (
    MerchantAgent,
    MerchantPolicy,
    NegotiationContext,
    NegotiationEngine,
    Stance,
    compute_sku_floor,
    new_negotiation_id,
)
from app.audit import AuditLogger, EventType, get_audit_logger
from app.checkout.adapter import CheckoutSagaAdapter
from app.checkout.inventory import InventoryService, OutOfStock
from app.config import settings
from app.matching import find_companions
from app.matching.catalog import load_products
from app.models import BundleStatus
from app.payments import (
    MockPaymentClient,
    PaymentClient,
    PaymentConfigError,
    RazorpayClient,
    SettlementBounds,
    validate_bounds,
)
from app.saga import (
    CoalitionSaga,
    LegStatus,
    SagaLeg,
    SagaPhase,
    SagaState,
    SagaStatus,
    SagaStore,
)

logger = logging.getLogger("checkout.service")

# Merchant -> Route linked-account id. Real acc_ ids come from env once the
# accounts exist; otherwise a demo placeholder (fine while Route is simulated).
LINKED_ACCOUNTS = {
    "merch_a_lumentech": settings.RAZORPAY_ACC_A or "acc_lumentech_test",
    "merch_b_carrycraft": settings.RAZORPAY_ACC_B or "acc_carrycraft_test",
}

# Per-merchant negotiation policies. The hard per-SKU discount ceiling is NOT
# here — it's derived from each product's real cost_price_inr + role in
# economics.py. What's genuinely merchant-level is stance (negotiating pace)
# and the minimum BLENDED discount that makes a coalition worth running at
# all. A is happy with almost any coalition (it already made its sale); B
# needs the deal to be compelling enough to be worth the acquisition effort.
_POLICIES = {
    "merch_a_lumentech": dict(min_viable_discount_pct=1.0, stance=Stance.AGGRESSIVE),
    "merch_b_carrycraft": dict(min_viable_discount_pct=2.0, stance=Stance.CONSERVATIVE),
}
_DEFAULT_POLICY = dict(min_viable_discount_pct=1.5, stance=Stance.CONSERVATIVE)


def _policy(merchant_id: str) -> MerchantPolicy:
    return MerchantPolicy(merchant_id=merchant_id,
                          **_POLICIES.get(merchant_id, _DEFAULT_POLICY))


def _default_payment_client() -> PaymentClient:
    """Real Razorpay client when enabled + configured; else the mock."""
    if settings.USE_REAL_RAZORPAY:
        try:
            client = RazorpayClient(route_enabled=settings.ROUTE_ENABLED)
            logger.info(
                "Using REAL Razorpay test client (route_enabled=%s).",
                settings.ROUTE_ENABLED,
            )
            return client
        except PaymentConfigError as exc:
            logger.warning(
                "USE_REAL_RAZORPAY set but client init failed (%s); "
                "falling back to MockPaymentClient.", exc,
            )
    return MockPaymentClient()


@dataclass
class PendingCheckout:
    correlation_id: str
    offer: object                    # BundleOffer
    offer_copy: str
    legs: list[dict]
    bounds: SettlementBounds
    otp: str
    expires_at: datetime
    confirmed: bool = False
    saga_id: str | None = None


@dataclass
class PendingPayment:
    """Between confirm (order created) and pay (payment verified)."""
    correlation_id: str
    saga_id: str
    bundle_id: str
    order_id: str
    amount_inr: int
    legs: list[dict]
    transfer_by_account: dict[str, str]
    settled: bool = False
    payment_id: str | None = None


class CheckoutService:
    def __init__(
        self,
        payment_client: PaymentClient | None = None,
        inventory: InventoryService | None = None,
        audit: AuditLogger | None = None,
        saga_store: SagaStore | None = None,
        confirmation_ttl_seconds: int | None = None,
    ):
        self._client = payment_client or _default_payment_client()
        self._payment_mode = (
            "razorpay_test" if isinstance(self._client, RazorpayClient) else "mock"
        )
        self._route_mode = (
            "live" if getattr(self._client, "route_enabled", False) else "simulated"
        )
        self._inventory = inventory or InventoryService()
        self._audit = audit or get_audit_logger()
        self._saga_store = saga_store or SagaStore()
        self._ttl = (
            confirmation_ttl_seconds
            if confirmation_ttl_seconds is not None
            else settings.OFFER_CONFIRMATION_TTL_SECONDS
        )
        self._pending: dict[str, PendingCheckout] = {}
        self._payments: dict[str, PendingPayment] = {}          # by correlation_id
        self._payments_by_order: dict[str, PendingPayment] = {}  # by order_id
        self._processed_webhook_ids: set[str] = set()
        self._products = load_products()

    # -- initiate ----------------------------------------------------------

    def initiate(self, product_id: str) -> dict:
        if product_id not in self._products:
            raise KeyError(f"Unknown product '{product_id}'.")

        correlation_id = f"sess_{uuid4().hex[:10]}"
        source = self._products[product_id]

        matches = find_companions(
            product_id, top_k=1,
            audit=self._audit, correlation_id=correlation_id,
        )
        if not matches:
            return {"matched": False, "offer": None,
                    "correlation_id": correlation_id,
                    "reason": "No cross-merchant companion cleared the threshold."}

        companion = matches[0].product
        affinity = matches[0].affinity_score

        pol_a = _policy(source.merchant_id)
        pol_b = _policy(companion.merchant_id)
        result = NegotiationEngine(
            MerchantAgent(pol_a), MerchantAgent(pol_b), self._audit
        ).negotiate(
            NegotiationContext(
                negotiation_id=new_negotiation_id(),
                product_a_id=source.product_id, product_b_id=companion.product_id,
                merchant_a_id=source.merchant_id, merchant_b_id=companion.merchant_id,
                price_a_inr=source.price_inr, price_b_inr=companion.price_inr,
                cost_a_inr=source.cost_price_inr, cost_b_inr=companion.cost_price_inr,
                role_a=source.product_role, role_b=companion.product_role,
                affinity_score=affinity, correlation_id=correlation_id,
            ),
            source, companion,
        )
        if result.status is not BundleStatus.AGREED or result.bundle is None:
            return {"matched": True, "offer": None,
                    "correlation_id": correlation_id,
                    "reason": result.reason}

        offer = result.bundle
        # Defense-in-depth: re-derive each SKU's discount ceiling independently
        # (same deterministic formula the negotiation used) rather than trust
        # the already-negotiated offer — bounds validation must stand on its
        # own two feet before any money moves. SettlementBounds wants the
        # REVENUE a merchant must retain as % of price (100 - ceiling), not
        # the smaller profit-margin-above-cost figure economics.py also
        # exposes as margin_floor_pct — those are different scales (e.g.
        # 98.2% revenue-retention vs 8.2% profit-margin for the same SKU).
        sku_a = compute_sku_floor(source.price_inr, source.cost_price_inr,
                                  source.product_role)
        sku_b = compute_sku_floor(companion.price_inr, companion.cost_price_inr,
                                  companion.product_role)
        bounds = SettlementBounds(
            price_a_inr=source.price_inr, price_b_inr=companion.price_inr,
            min_margin_a_pct=100 - sku_a.discount_ceiling_pct,
            min_margin_b_pct=100 - sku_b.discount_ceiling_pct,
        )
        violations = validate_bounds(offer, bounds, settings.MAX_TRANSACTION_INR)
        if violations:
            self._audit.log(
                correlation_id=correlation_id, event_type=EventType.FAILURE,
                actor="checkout", reasoning="Offer rejected by bounds: "
                + "; ".join(violations),
                decision={"violations": violations},
            )
            return {"matched": True, "offer": None,
                    "correlation_id": correlation_id,
                    "reason": "Offer failed safety bounds."}

        legs = [
            {"merchant_id": offer.merchant_a_id, "product_id": offer.product_a_id,
             "account": LINKED_ACCOUNTS.get(offer.merchant_a_id, "acc_unknown_a"),
             "amount_inr": offer.merchant_a_amount_inr},
            {"merchant_id": offer.merchant_b_id, "product_id": offer.product_b_id,
             "account": LINKED_ACCOUNTS.get(offer.merchant_b_id, "acc_unknown_b"),
             "amount_inr": offer.merchant_b_amount_inr},
        ]
        otp = f"{secrets.randbelow(1_000_000):06d}"
        self._pending[correlation_id] = PendingCheckout(
            correlation_id=correlation_id, offer=offer,
            offer_copy=result.offer_copy or "", legs=legs, bounds=bounds, otp=otp,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self._ttl),
        )

        return {
            "matched": True,
            "correlation_id": correlation_id,
            "offer": {
                "bundle_id": offer.bundle_id,
                "product_a": {"id": offer.product_a_id, "name": source.name,
                              "merchant": offer.merchant_a_id,
                              "amount_inr": offer.merchant_a_amount_inr,
                              "price_inr": source.price_inr,
                              "mrp_inr": source.effective_mrp},
                "product_b": {"id": offer.product_b_id, "name": companion.name,
                              "merchant": offer.merchant_b_id,
                              "amount_inr": offer.merchant_b_amount_inr,
                              "price_inr": companion.price_inr,
                              "mrp_inr": companion.effective_mrp},
                "original_total_inr": offer.original_total_inr,
                "discount_pct": offer.discount_pct,               # blended
                "merchant_a_discount_pct": offer.merchant_a_discount_pct,
                "merchant_b_discount_pct": offer.merchant_b_discount_pct,
                "bundle_price_inr": offer.bundle_price_inr,
                # MRP-based headline savings (what a shopper actually sees).
                "mrp_total_inr": source.effective_mrp + companion.effective_mrp,
                "savings_vs_mrp_pct": round(
                    (source.effective_mrp + companion.effective_mrp
                     - offer.bundle_price_inr)
                    / (source.effective_mrp + companion.effective_mrp) * 100, 1
                ),
                "affinity_score": round(offer.affinity_score, 3),
                "copy": result.offer_copy,
            },
            # In production the OTP is sent to the customer, never returned.
            "otp_for_demo": otp,
            "expires_at": self._pending[correlation_id].expires_at.isoformat(),
        }

    # -- confirm (OTP gate -> reserve + create order) ----------------------

    def confirm(self, correlation_id: str, otp: str) -> dict:
        pending = self._pending.get(correlation_id)
        if pending is None:
            raise KeyError(f"No pending checkout for '{correlation_id}'.")

        # HUMAN GATE.
        if datetime.now(timezone.utc) >= pending.expires_at:
            self._audit.log(
                correlation_id=correlation_id, event_type=EventType.FAILURE,
                actor="checkout",
                reasoning="Offer expired before confirmation; nothing reserved.",
                decision={"settled": False, "status": "expired"},
            )
            return {"correlation_id": correlation_id, "status": "expired",
                    "settled": False, "reason": "Offer expired."}
        if not secrets.compare_digest(otp, pending.otp):
            self._audit.log(
                correlation_id=correlation_id, event_type=EventType.FAILURE,
                actor="checkout", reasoning="Invalid OTP; checkout halted.",
                decision={"settled": False, "reason": "invalid_otp"},
            )
            return {"correlation_id": correlation_id, "status": "rejected",
                    "settled": False, "reason": "Invalid OTP."}

        self._audit.log(
            correlation_id=correlation_id,
            event_type=EventType.CUSTOMER_CONFIRMATION, actor="customer",
            reasoning="Customer passed the OTP human gate. Reserving inventory "
                      "and creating the payment order.",
            decision={"confirmed": True},
        )

        pp = self._prepare(correlation_id, pending)
        if pp is None:
            return {"correlation_id": correlation_id, "status": "failed",
                    "settled": False, "reason": "All items are out of stock."}

        # Real Razorpay: hand the order to the browser to actually collect
        # payment via Checkout. Mock: no real payment, settle immediately.
        if isinstance(self._client, RazorpayClient):
            return {
                "correlation_id": correlation_id,
                "status": "awaiting_payment",
                "needs_payment": True,
                "order_id": pp.order_id,
                "razorpay_key_id": self._client.key_id,
                "amount_inr": pp.amount_inr,
                "amount_paise": pp.amount_inr * 100,
                "currency": "INR",
                "payment_mode": self._payment_mode,
                "route_mode": self._route_mode,
                "prefill": {"name": "Test Customer",
                            "email": "test@example.com", "contact": "9999999999"},
            }
        return self._settle(pp, payment_id=f"pay_mock_{pp.order_id}")

    # -- pay (verify signature server-side -> continue saga) ---------------

    def pay(
        self, correlation_id: str, razorpay_payment_id: str,
        razorpay_order_id: str, razorpay_signature: str,
    ) -> dict:
        pp = self._payments.get(correlation_id)
        if pp is None:
            raise KeyError(f"No order awaiting payment for '{correlation_id}'.")
        if pp.settled:
            return {"correlation_id": correlation_id, "status": "completed",
                    "settled": True, "order_id": pp.order_id,
                    "payment_id": pp.payment_id, "note": "already settled"}

        verified = self._client.verify_payment_signature(
            razorpay_order_id, razorpay_payment_id, razorpay_signature
        )
        if not verified:
            self._audit.log(
                correlation_id=correlation_id, event_type=EventType.FAILURE,
                actor="razorpay",
                reasoning="Payment signature verification FAILED server-side. "
                          "Rejecting and releasing reservations.",
                decision={"payment_id": razorpay_payment_id, "verified": False},
            )
            self._compensate_unpaid(pp, "payment signature verification failed")
            return {"correlation_id": correlation_id, "status": "failed",
                    "settled": False, "order_id": pp.order_id,
                    "reason": "Payment signature verification failed."}

        self._audit.log(
            correlation_id=correlation_id, event_type=EventType.PAYMENT_INITIATED,
            actor="razorpay",
            reasoning=f"Payment {razorpay_payment_id} captured and signature "
                      f"verified server-side. Continuing saga to the split.",
            decision={"payment_id": razorpay_payment_id,
                      "order_id": razorpay_order_id, "verified": True},
        )
        return self._settle(pp, razorpay_payment_id)

    # -- failure simulation (full saga, forced failures, no real payment) --

    def simulate(self, product_id: str, simulate: dict | None = None) -> dict:
        init = self.initiate(product_id)
        if not init.get("offer"):
            return {"status": "failed", "settled": False,
                    "reason": init.get("reason", "No offer.")}
        cid = init["correlation_id"]
        pending = self._pending[cid]
        sim = simulate or {}
        confirmed = not bool(sim.get("confirmation_timeout"))
        if confirmed:
            self._audit.log(
                correlation_id=cid, event_type=EventType.CUSTOMER_CONFIRMATION,
                actor="customer",
                reasoning="Customer confirmed (simulation) — running saga.",
                decision={"confirmed": True},
            )
        merchant_b_id = pending.legs[1]["merchant_id"]
        adapter = CheckoutSagaAdapter(
            legs=pending.legs, inventory=self._inventory,
            payment_client=self._client, confirmed=confirmed,
            bundle_id=pending.offer.bundle_id,
            fail_inventory_for={merchant_b_id} if sim.get("inventory_fail") else set(),
            fail_capture=bool(sim.get("capture_fail")),
            fail_transfer=bool(sim.get("transfer_fail")),
        )
        saga = CoalitionSaga(adapter, audit=self._audit, store=self._saga_store)
        state = saga.run(cid, pending.offer.bundle_id,
                         [SagaLeg(**leg) for leg in pending.legs])
        return self._result(state, adapter, payment_id=None)

    # -- internals ---------------------------------------------------------

    def _prepare(self, correlation_id: str, pending) -> PendingPayment | None:
        """Reserve inventory (with degradation) and create the real order."""
        saga_legs: list[SagaLeg] = []
        reserved_any = False
        for leg in pending.legs:
            sl = SagaLeg(**leg)
            try:
                sl.reservation_id = self._inventory.reserve(leg["product_id"])
                sl.status = LegStatus.RESERVED
                reserved_any = True
                self._audit.log(
                    correlation_id=correlation_id,
                    event_type=EventType.SAGA_STEP_COMPLETED, actor="inventory",
                    reasoning=f"Reserved inventory for {leg['merchant_id']}.",
                    decision={"reservation_id": sl.reservation_id},
                )
            except OutOfStock as exc:
                sl.status = LegStatus.DROPPED
                sl.note = str(exc)
                self._audit.log(
                    correlation_id=correlation_id,
                    event_type=EventType.SAGA_STEP_FAILED, actor="inventory",
                    reasoning=f"Inventory reservation failed for {leg['merchant_id']}: "
                              f"{exc}. Dropping this leg (customer not charged for it).",
                    decision={"dropped": True},
                )
            saga_legs.append(sl)

        surviving = [l for l in saga_legs if l.status is LegStatus.RESERVED]
        if not surviving:
            self._audit.log(
                correlation_id=correlation_id, event_type=EventType.SAGA_FAILED,
                actor="saga", reasoning="No inventory available; nothing charged.",
                decision={"status": "failed"},
            )
            return None

        amount = sum(l.amount_inr for l in surviving)
        transfers = [
            {"account": l.account, "amount": l.amount_inr * 100, "currency": "INR",
             "on_hold": True,
             "notes": {"bundle_id": pending.offer.bundle_id,
                       "merchant_id": l.merchant_id}}
            for l in surviving
        ]
        order = self._client.create_order_with_transfers(
            amount_paise=amount * 100, currency="INR",
            receipt=f"rcpt_{pending.offer.bundle_id}", transfers=transfers,
            notes={"bundle_id": pending.offer.bundle_id,
                   "correlation_id": correlation_id},
        )
        order_id = order["id"]
        transfer_by_account = {
            t["recipient"]: t["id"] for t in order.get("transfers", [])
        }

        state = SagaState(
            saga_id=f"saga_{uuid4().hex[:12]}",
            correlation_id=correlation_id, bundle_id=pending.offer.bundle_id,
            status=SagaStatus.RUNNING, phase=SagaPhase.TRANSFER,
            order_id=order_id, capture_id=None, amount_captured_inr=0,
            legs=saga_legs,
        )
        self._saga_store.save(state)
        self._audit.log(
            correlation_id=correlation_id, event_type=EventType.SAGA_STARTED,
            actor="saga",
            reasoning=f"Saga {state.saga_id}: inventory reserved, order {order_id} "
                      f"created for Rs.{amount}. Awaiting customer payment.",
            inputs={"saga_id": state.saga_id, "order_id": order_id},
        )
        self._audit.log(
            correlation_id=correlation_id, event_type=EventType.PAYMENT_INITIATED,
            actor="payment",
            reasoning=f"Razorpay order {order_id} created for Rs.{amount}; "
                      f"transfers held pending payment + confirmation.",
            decision={"order_id": order_id, "amount_inr": amount},
        )

        pp = PendingPayment(
            correlation_id=correlation_id, saga_id=state.saga_id,
            bundle_id=pending.offer.bundle_id, order_id=order_id,
            amount_inr=amount, legs=pending.legs,
            transfer_by_account=transfer_by_account,
        )
        self._payments[correlation_id] = pp
        self._payments_by_order[order_id] = pp
        return pp

    def _settle(self, pp: PendingPayment, payment_id: str) -> dict:
        state = self._saga_store.load(pp.saga_id)
        state.capture_id = payment_id
        state.amount_captured_inr = pp.amount_inr
        self._saga_store.save(state)

        adapter = CheckoutSagaAdapter(
            legs=pp.legs, inventory=self._inventory, payment_client=self._client,
            confirmed=True, bundle_id=pp.bundle_id,
            transfer_by_account=pp.transfer_by_account,
            captured_inr=pp.amount_inr, order_id=pp.order_id,
        )
        final = CoalitionSaga(
            adapter, audit=self._audit, store=self._saga_store
        ).resume(pp.saga_id)
        pp.settled = final.status in (SagaStatus.COMPLETED,
                                      SagaStatus.PARTIALLY_COMPLETED)
        pp.payment_id = payment_id
        return self._result(final, adapter, payment_id)

    def _compensate_unpaid(self, pp: PendingPayment, reason: str) -> None:
        state = self._saga_store.load(pp.saga_id)
        for leg in state.legs:
            if leg.reservation_id and not leg.reservation_released:
                self._inventory.release(leg.reservation_id)
                leg.reservation_released = True
                leg.status = LegStatus.COMPENSATED
                self._audit.log(
                    correlation_id=pp.correlation_id,
                    event_type=EventType.COMPENSATION_EXECUTED, actor="inventory",
                    reasoning=f"Released reservation for {leg.merchant_id}. "
                              f"Reason: {reason}",
                    decision={"reservation_id": leg.reservation_id},
                )
        state.status = SagaStatus.COMPENSATED
        state.phase = SagaPhase.DONE
        state.reason = reason
        self._saga_store.save(state)
        self._audit.log(
            correlation_id=pp.correlation_id, event_type=EventType.SAGA_FAILED,
            actor="saga",
            reasoning=f"Compensated (no capture). {reason} No money moved.",
            decision={"status": "compensated", "net_charge_inr": 0},
        )

    def _result(self, state, adapter, payment_id: str | None) -> dict:
        return {
            "correlation_id": state.correlation_id,
            "saga_id": state.saga_id,
            "status": state.status.value,
            "settled": state.status in (SagaStatus.COMPLETED,
                                        SagaStatus.PARTIALLY_COMPLETED),
            "order_id": adapter.order_id or state.order_id,
            "payment_id": payment_id,
            "payment_mode": self._payment_mode,
            "route_mode": self._route_mode,
            "net_customer_charge_inr": adapter.net_customer_charge(),
            "stuck_money_inr": adapter.stuck_money(),
            "transfers": [
                {"transfer_id": tid, "account": t["account"],
                 "amount_inr": t["amount"], "reversed": t["reversed"]}
                for tid, t in adapter.transfers.items()
            ],
            "legs": [
                {"merchant_id": l.merchant_id, "amount_inr": l.amount_inr,
                 "status": l.status.value, "note": l.note}
                for l in state.legs
            ],
            "reason": state.reason,
        }

    # -- webhook (server-side source of truth) -----------------------------

    def handle_webhook(self, event_id: str, event_type: str, payload: dict) -> dict:
        if event_id and event_id in self._processed_webhook_ids:
            return {"status": "duplicate"}
        if event_id:
            self._processed_webhook_ids.add(event_id)

        entity = (
            payload.get("payload", {}).get("payment", {}).get("entity", {})
        )
        order_id = entity.get("order_id")
        payment_id = entity.get("id")
        pp = self._payments_by_order.get(order_id) if order_id else None
        cid = pp.correlation_id if pp else (order_id or "webhook")

        if event_type == "payment.captured":
            self._audit.log(
                correlation_id=cid, event_type=EventType.PAYMENT_INITIATED,
                actor="webhook",
                reasoning=f"Webhook payment.captured for {payment_id} — "
                          f"server-side source of truth.",
                decision={"payment_id": payment_id, "order_id": order_id},
            )
            if pp and not pp.settled:
                self._settle(pp, payment_id)
        elif event_type == "payment.failed":
            self._audit.log(
                correlation_id=cid, event_type=EventType.FAILURE, actor="webhook",
                reasoning=f"Webhook payment.failed for {payment_id}.",
                decision={"payment_id": payment_id, "order_id": order_id},
            )
            if pp and not pp.settled:
                self._compensate_unpaid(pp, "webhook payment.failed")
        return {"status": "ok", "event_type": event_type}

    def get_pending(self, correlation_id: str) -> PendingCheckout | None:
        return self._pending.get(correlation_id)


_checkout_service: CheckoutService | None = None


def get_checkout_service() -> CheckoutService:
    global _checkout_service
    if _checkout_service is None:
        _checkout_service = CheckoutService()
    return _checkout_service
