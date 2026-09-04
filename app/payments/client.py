"""Razorpay client wrapper (TEST MODE) + an interchangeable mock.

The rest of the payment layer depends on the ``PaymentClient`` interface, not on
the Razorpay SDK directly. That keeps the safety logic (bounds + human gate)
testable and lets us run the full flow locally with ``MockPaymentClient`` before
real Route linked accounts exist.

All amounts crossing this boundary are in PAISE (Razorpay's unit).
"""
import logging
from typing import Protocol, runtime_checkable

from app.config import settings

logger = logging.getLogger("payments.client")


class PaymentConfigError(RuntimeError):
    """Raised when Razorpay credentials are missing/invalid."""


@runtime_checkable
class PaymentClient(Protocol):
    key_id: str

    def create_order_with_transfers(
        self,
        *,
        amount_paise: int,
        currency: str,
        receipt: str,
        transfers: list[dict],
        notes: dict | None = None,
    ) -> dict:
        """Create ONE order whose captured amount fans out to linked accounts."""
        ...

    def release_transfer(self, transfer_id: str) -> dict:
        """Release a held transfer (on_hold -> 0) so it can settle."""
        ...

    def verify_payment_signature(
        self, order_id: str, payment_id: str, signature: str
    ) -> bool:
        """Server-side verification of a Checkout callback. Never trust client."""
        ...

    def refund_payment(self, payment_id: str, amount_inr: int) -> dict: ...

    def reverse_transfer(self, transfer_id: str, amount_inr: int) -> dict: ...


class RazorpayClient:
    """Thin wrapper over the Razorpay SDK. TEST MODE credentials only.

    ``route_enabled`` controls the split behaviour:
      * True  — the order is created WITH a real ``transfers`` array (real
                Route split; requires the Route feature active on the account).
      * False — a REAL order is created for the total amount (real order_ id),
                but the per-merchant transfers are SIMULATED over it. This lets
                us hit the real Orders API while Route activation/KYC is pending.
    """

    def __init__(
        self,
        key_id: str | None = None,
        key_secret: str | None = None,
        route_enabled: bool = False,
    ):
        key_id = key_id or settings.RAZORPAY_KEY_ID
        key_secret = key_secret or settings.RAZORPAY_KEY_SECRET
        if not key_id or not key_secret or key_id == "rzp_test_placeholder":
            raise PaymentConfigError(
                "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not set. "
                "Use test-mode keys, or inject MockPaymentClient for local runs."
            )
        if not key_id.startswith("rzp_test_"):
            # Guardrail: this project is test-mode only.
            logger.warning(
                "RAZORPAY_KEY_ID does not look like a test key (rzp_test_...). "
                "This project is intended for TEST MODE only."
            )

        import razorpay  # imported lazily so tests/mock don't need the SDK

        self._client = razorpay.Client(auth=(key_id, key_secret))
        self.key_id = key_id
        self.route_enabled = route_enabled

    def create_order_with_transfers(
        self,
        *,
        amount_paise: int,
        currency: str,
        receipt: str,
        transfers: list[dict],
        notes: dict | None = None,
    ) -> dict:
        data = {
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt,
        }
        if notes:
            data["notes"] = notes
        if self.route_enabled:
            data["transfers"] = transfers

        order = dict(self._client.order.create(data=data))  # REAL order

        if not self.route_enabled:
            # Route not active on this account — synthesize held-transfer stubs
            # over the real order so the saga's per-leg flow still works. These
            # ids are clearly marked simulated.
            order["transfers"] = [
                {
                    "id": f"trf_sim_{order['id']}_{i}",
                    "recipient": t["account"],
                    "amount": t["amount"],
                    "on_hold": t.get("on_hold", False),
                    "simulated": True,
                }
                for i, t in enumerate(transfers)
            ]
        return order

    def release_transfer(self, transfer_id: str) -> dict:
        if self.route_enabled and not transfer_id.startswith("trf_sim_"):
            # PATCH /v1/transfers/:id with on_hold=0 releases the real hold.
            return self._client.transfer.edit(transfer_id, {"on_hold": 0})
        return {"id": transfer_id, "on_hold": False, "status": "processed",
                "simulated": True}

    def verify_payment_signature(
        self, order_id: str, payment_id: str, signature: str
    ) -> bool:
        import razorpay

        try:
            self._client.utility.verify_payment_signature({
                "razorpay_order_id": order_id,
                "razorpay_payment_id": payment_id,
                "razorpay_signature": signature,
            })
            return True
        except razorpay.errors.SignatureVerificationError:
            return False

    def verify_webhook_signature(
        self, body: str, signature: str, secret: str
    ) -> bool:
        import razorpay

        try:
            self._client.utility.verify_webhook_signature(body, signature, secret)
            return True
        except razorpay.errors.SignatureVerificationError:
            return False

    def refund_payment(self, payment_id: str, amount_inr: int) -> dict:
        return self._client.payment.refund(
            payment_id, {"amount": amount_inr * 100}
        )

    def reverse_transfer(self, transfer_id: str, amount_inr: int) -> dict:
        if transfer_id.startswith("trf_sim_"):
            return {"id": transfer_id, "reversed": True, "simulated": True}
        # POST /v1/transfers/:id/reversals
        return self._client.transfer.reverse(
            transfer_id, {"amount": amount_inr * 100}
        )


class MockPaymentClient:
    """In-memory stand-in mirroring the Razorpay Route response shapes.

    For local demos and tests only — no money moves. Tracks which transfers
    were released so the human-gate behaviour can be asserted.
    """

    key_id = "rzp_test_mock"
    route_enabled = False

    def __init__(self):
        self.orders: list[dict] = []
        self.released: list[str] = []
        self._on_hold: dict[str, bool] = {}
        self._counter = 0

    def create_order_with_transfers(
        self,
        *,
        amount_paise: int,
        currency: str,
        receipt: str,
        transfers: list[dict],
        notes: dict | None = None,
    ) -> dict:
        self._counter += 1
        order_id = f"order_mock_{self._counter:06d}"
        resp_transfers = []
        for i, t in enumerate(transfers):
            tid = f"trf_mock_{self._counter:06d}_{i}"
            self._on_hold[tid] = bool(t.get("on_hold", False))
            resp_transfers.append({
                "id": tid,
                "entity": "transfer",
                "status": "created",
                "recipient": t["account"],
                "amount": t["amount"],
                "currency": t.get("currency", currency),
                "on_hold": self._on_hold[tid],
                "on_hold_until": t.get("on_hold_until"),
                "recipient_settlement_id": None,
            })
        order = {
            "id": order_id,
            "entity": "order",
            "amount": amount_paise,
            "currency": currency,
            "receipt": receipt,
            "status": "created",
            "transfers": resp_transfers,
        }
        self.orders.append(order)
        return order

    def release_transfer(self, transfer_id: str) -> dict:
        self._on_hold[transfer_id] = False
        self.released.append(transfer_id)
        return {
            "id": transfer_id,
            "entity": "transfer",
            "on_hold": False,
            "status": "processed",
            "recipient_settlement_id": f"setl_mock_{transfer_id}",
        }

    def verify_payment_signature(
        self, order_id: str, payment_id: str, signature: str
    ) -> bool:
        return True  # no real payment in mock mode

    def refund_payment(self, payment_id: str, amount_inr: int) -> dict:
        return {"id": f"rfnd_mock_{payment_id}", "amount": amount_inr * 100}

    def reverse_transfer(self, transfer_id: str, amount_inr: int) -> dict:
        return {"id": transfer_id, "reversed": True}
