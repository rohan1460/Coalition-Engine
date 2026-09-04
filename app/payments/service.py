"""Payment orchestration with a hard human safety gate.

Flow:
  1. create_bundle_order() — validate bounds, then create ONE Razorpay order
     whose transfers to both merchants are created **on hold**. Money is
     captured but parked; nothing settles yet. An OTP is issued and the pending
     settlement is given a TTL.
  2. confirm_and_settle() — the customer's OTP must be validated before the held
     transfers are released. Wrong OTP or an expired offer -> nothing settles.

The on-hold transfer IS the human gate: settlement is physically impossible
until an explicit, time-bounded customer confirmation releases it.
"""
import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum

from app.audit import AuditLogger, EventType, get_audit_logger
from app.config import settings
from app.models import BundleOffer
from app.payments.bounds import BoundsViolation, SettlementBounds, validate_bounds
from app.payments.client import PaymentClient

logger = logging.getLogger("payments.service")

INR_TO_PAISE = 100


class SettlementStatus(str, Enum):
    PENDING = "pending"      # order created, transfers held, awaiting OTP
    SETTLED = "settled"      # confirmed + transfers released
    EXPIRED = "expired"      # TTL elapsed with no confirmation
    FAILED = "failed"        # rejected (bounds) or confirmation failure


class ConfirmationError(Exception):
    """Raised when a confirmation is invalid or too late."""


@dataclass
class PendingSettlement:
    order_id: str
    bundle_id: str
    correlation_id: str
    amount_inr: int
    transfer_ids: list[str]
    otp: str                       # demo/test only — real world: sent via SMS
    expires_at: datetime
    status: SettlementStatus = SettlementStatus.PENDING
    released_transfer_ids: list[str] = field(default_factory=list)

    def is_expired(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return now >= self.expires_at


class PaymentService:
    def __init__(
        self,
        client: PaymentClient,
        audit: AuditLogger | None = None,
        cap_inr: int | None = None,
        confirmation_ttl_seconds: int | None = None,
    ):
        self._client = client
        self._audit = audit or get_audit_logger()
        self._cap_inr = cap_inr if cap_inr is not None else settings.MAX_TRANSACTION_INR
        self._ttl = (
            confirmation_ttl_seconds
            if confirmation_ttl_seconds is not None
            else settings.OFFER_CONFIRMATION_TTL_SECONDS
        )
        self._pending: dict[str, PendingSettlement] = {}

    # -- step 1: create the held order -------------------------------------

    def create_bundle_order(
        self,
        offer: BundleOffer,
        bounds: SettlementBounds,
        linked_accounts: dict[str, str],
        correlation_id: str,
        receipt: str | None = None,
    ) -> PendingSettlement:
        # --- BOUNDS: validated before any API call ---
        violations = validate_bounds(offer, bounds, self._cap_inr)
        acct_a = linked_accounts.get(offer.merchant_a_id)
        acct_b = linked_accounts.get(offer.merchant_b_id)
        if not acct_a or not acct_b:
            violations.append("missing linked account id for one or both merchants")

        if violations:
            self._audit.log(
                correlation_id=correlation_id,
                event_type=EventType.FAILURE,
                actor="payment_guard",
                reasoning=(
                    "Rejected before any Razorpay call — bounds violated: "
                    + "; ".join(violations)
                ),
                inputs={"bundle_id": offer.bundle_id, "cap_inr": self._cap_inr},
                decision={"violations": violations, "api_called": False},
            )
            raise BoundsViolation(violations)

        # --- build the on-hold transfers (money captured, not settled) ---
        transfers = [
            self._transfer(offer.merchant_a_id, acct_a, offer.merchant_a_amount_inr,
                           offer.bundle_id),
            self._transfer(offer.merchant_b_id, acct_b, offer.merchant_b_amount_inr,
                           offer.bundle_id),
        ]
        order = self._client.create_order_with_transfers(
            amount_paise=offer.bundle_price_inr * INR_TO_PAISE,
            currency="INR",
            receipt=receipt or f"rcpt_{offer.bundle_id}",
            transfers=transfers,
            notes={"bundle_id": offer.bundle_id, "correlation_id": correlation_id},
        )

        transfer_ids = [t["id"] for t in order.get("transfers", [])]
        otp = f"{secrets.randbelow(1_000_000):06d}"
        pending = PendingSettlement(
            order_id=order["id"],
            bundle_id=offer.bundle_id,
            correlation_id=correlation_id,
            amount_inr=offer.bundle_price_inr,
            transfer_ids=transfer_ids,
            otp=otp,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=self._ttl),
        )
        self._pending[pending.order_id] = pending

        self._audit.log(
            correlation_id=correlation_id,
            event_type=EventType.PAYMENT_INITIATED,
            actor="payment_service",
            reasoning=(
                f"Order {order['id']} created for Rs.{offer.bundle_price_inr}; "
                f"both transfers ON HOLD pending customer OTP. Expires in "
                f"{self._ttl}s. Bounds passed."
            ),
            inputs={
                "bundle_id": offer.bundle_id,
                "amount_inr": offer.bundle_price_inr,
                "split": {
                    offer.merchant_a_id: offer.merchant_a_amount_inr,
                    offer.merchant_b_id: offer.merchant_b_amount_inr,
                },
            },
            decision={
                "order_id": order["id"],
                "transfer_ids": transfer_ids,
                "on_hold": True,
                "otp_issued": True,  # value never logged
                "expires_at": pending.expires_at.isoformat(),
            },
        )
        return pending

    # -- step 2: confirm + settle ------------------------------------------

    def confirm_and_settle(self, order_id: str, otp: str) -> PendingSettlement:
        pending = self._pending.get(order_id)
        if pending is None:
            raise ConfirmationError(f"Unknown order '{order_id}'.")

        cid = pending.correlation_id

        # Expiry check FIRST — an unconfirmed offer must not settle.
        if pending.status is SettlementStatus.PENDING and pending.is_expired():
            pending.status = SettlementStatus.EXPIRED

        if pending.status is not SettlementStatus.PENDING:
            self._audit.log(
                correlation_id=cid,
                event_type=EventType.FAILURE,
                actor="payment_service",
                reasoning=(
                    f"Confirmation rejected: offer is {pending.status.value} "
                    f"(not pending). No settlement triggered."
                ),
                inputs={"order_id": order_id},
                decision={"settled": False, "status": pending.status.value},
            )
            raise ConfirmationError(f"Offer is {pending.status.value}.")

        if not secrets.compare_digest(otp, pending.otp):
            self._audit.log(
                correlation_id=cid,
                event_type=EventType.FAILURE,
                actor="payment_service",
                reasoning="Invalid OTP — customer confirmation failed. No settlement.",
                inputs={"order_id": order_id},
                decision={"settled": False, "reason": "invalid_otp"},
            )
            raise ConfirmationError("Invalid OTP.")

        # Explicit, valid, in-time human confirmation.
        self._audit.log(
            correlation_id=cid,
            event_type=EventType.CUSTOMER_CONFIRMATION,
            actor="customer",
            reasoning="Customer confirmed the bundle with a valid OTP in time.",
            inputs={"order_id": order_id},
            decision={"confirmed": True},
        )

        # Release each held transfer -> now the money can settle.
        for tid in pending.transfer_ids:
            self._client.release_transfer(tid)
            pending.released_transfer_ids.append(tid)

        pending.status = SettlementStatus.SETTLED
        self._audit.log(
            correlation_id=cid,
            event_type=EventType.SPLIT_EXECUTED,
            actor="payment_service",
            reasoning=(
                f"Released {len(pending.released_transfer_ids)} held transfer(s); "
                f"Rs.{pending.amount_inr} now settling to both merchants."
            ),
            inputs={"order_id": order_id},
            decision={
                "settled": True,
                "released_transfer_ids": pending.released_transfer_ids,
            },
        )
        return pending

    # -- housekeeping ------------------------------------------------------

    def expire_stale(self) -> list[str]:
        """Transition any lapsed pending offers to EXPIRED and log it."""
        expired: list[str] = []
        for pending in self._pending.values():
            if pending.status is SettlementStatus.PENDING and pending.is_expired():
                pending.status = SettlementStatus.EXPIRED
                expired.append(pending.order_id)
                self._audit.log(
                    correlation_id=pending.correlation_id,
                    event_type=EventType.ROLLBACK,
                    actor="payment_service",
                    reasoning=(
                        f"Offer {pending.order_id} expired without confirmation; "
                        f"held transfers left unreleased (no settlement)."
                    ),
                    inputs={"order_id": pending.order_id},
                    decision={"status": "expired", "settled": False},
                )
        return expired

    def get_pending(self, order_id: str) -> PendingSettlement | None:
        return self._pending.get(order_id)

    @staticmethod
    def _transfer(merchant_id: str, account: str, amount_inr: int,
                  bundle_id: str) -> dict:
        return {
            "account": account,
            "amount": amount_inr * INR_TO_PAISE,
            "currency": "INR",
            "on_hold": True,  # HUMAN GATE: released only after OTP confirmation
            "notes": {"bundle_id": bundle_id, "merchant_id": merchant_id},
        }
