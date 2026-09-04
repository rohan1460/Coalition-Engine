"""Concrete SagaAdapter wiring inventory + the Route payment client.

Constructed fresh per confirmed checkout (it is stateful). It translates the
saga's abstract steps onto real services:
  reserve_inventory  -> InventoryService.reserve
  capture_payment    -> create ONE Razorpay order with on-hold transfers for the
                        legs that were successfully reserved
  execute_transfer   -> release the held transfer for that leg (settlement)
  compensations      -> release inventory / reverse transfer / refund

A small money ledger is kept so the demo can prove no funds are left stuck.
For the mock client, refund/reverse are ledger-only; a real client would call
Razorpay's refund + transfer-reversal APIs here.
"""
import logging

from app.checkout.inventory import InventoryService, OutOfStock
from app.payments.client import PaymentClient
from app.saga.adapter import InventoryError, PaymentCaptureError, TransferError

logger = logging.getLogger("checkout.adapter")

INR_TO_PAISE = 100


class CheckoutSagaAdapter:
    def __init__(
        self,
        legs: list[dict],          # [{merchant_id, product_id, account, amount_inr}]
        inventory: InventoryService,
        payment_client: PaymentClient,
        confirmed: bool,
        bundle_id: str,
        fail_inventory_for: set[str] | None = None,
        fail_capture: bool = False,
        fail_transfer: bool = False,
        # Hydration for resuming the transfer step after a real payment.
        transfer_by_account: dict[str, str] | None = None,
        captured_inr: int = 0,
        order_id: str | None = None,
    ):
        self._legs = legs
        self._inventory = inventory
        self._client = payment_client
        self._confirmed = confirmed
        self._bundle_id = bundle_id
        # Failure-injection flags (used by the Failure Simulation panel).
        self._fail_inventory_for = fail_inventory_for or set()
        self._fail_capture = fail_capture
        self._fail_transfer = fail_transfer

        self._account_by_merchant = {l["merchant_id"]: l["account"] for l in legs}
        self._amount_by_merchant = {l["merchant_id"]: l["amount_inr"] for l in legs}
        self._reserved_merchants: list[str] = []
        self._transfer_by_account: dict[str, str] = transfer_by_account or {}

        # ledger (hydrated when resuming after payment)
        self.captured_total = captured_inr
        self.refunded_total = 0
        self.transfers: dict[str, dict] = {}
        self.order_id: str | None = order_id

    # -- inventory ---------------------------------------------------------

    def reserve_inventory(self, merchant_id: str, product_id: str) -> str:
        if merchant_id in self._fail_inventory_for:
            raise InventoryError(
                f"simulated inventory lock failure for {merchant_id}"
            )
        try:
            rid = self._inventory.reserve(product_id)
        except OutOfStock as exc:
            raise InventoryError(str(exc)) from exc
        self._reserved_merchants.append(merchant_id)
        return rid

    def release_inventory(self, reservation_id: str) -> None:
        self._inventory.release(reservation_id)

    # -- confirmation gate -------------------------------------------------

    def is_confirmed(self) -> bool:
        return self._confirmed

    # -- payment -----------------------------------------------------------

    def capture_payment(self, order_id: str | None, amount_inr: int) -> str:
        if self._fail_capture:
            raise PaymentCaptureError("simulated payment capture failure")
        # Build transfers only for the legs that were actually reserved.
        transfers = [
            {
                "account": self._account_by_merchant[m],
                "amount": self._amount_by_merchant[m] * INR_TO_PAISE,
                "currency": "INR",
                "on_hold": True,  # held until the transfer step releases it
                "notes": {"bundle_id": self._bundle_id, "merchant_id": m},
            }
            for m in self._reserved_merchants
        ]
        order = self._client.create_order_with_transfers(
            amount_paise=amount_inr * INR_TO_PAISE,
            currency="INR",
            receipt=f"rcpt_{self._bundle_id}",
            transfers=transfers,
        )
        self.order_id = order["id"]
        for t in order.get("transfers", []):
            self._transfer_by_account[t["recipient"]] = t["id"]
        self.captured_total += amount_inr
        return order["id"]

    def refund_payment(self, capture_id: str, amount_inr: int) -> None:
        # Real refund when the client supports it (razorpay); ledger otherwise.
        try:
            self._client.refund_payment(capture_id, amount_inr)
        except Exception as exc:  # never let a compensation crash the saga
            logger.warning("refund_payment fell back to ledger only: %s", exc)
        self.refunded_total += amount_inr

    # -- transfers ---------------------------------------------------------

    def execute_transfer(self, account: str, amount_inr: int) -> str:
        if self._fail_transfer:
            raise TransferError(f"simulated Route transfer failure for {account}")
        tid = self._transfer_by_account[account]
        self._client.release_transfer(tid)     # release the hold -> settles
        self.transfers[tid] = {"account": account, "amount": amount_inr,
                               "reversed": False}
        return tid

    def reverse_transfer(self, transfer_id: str) -> None:
        amount = self.transfers.get(transfer_id, {}).get("amount", 0)
        try:
            self._client.reverse_transfer(transfer_id, amount)
        except Exception as exc:
            logger.warning("reverse_transfer fell back to ledger only: %s", exc)
        if transfer_id in self.transfers:
            self.transfers[transfer_id]["reversed"] = True

    # -- ledger ------------------------------------------------------------

    def net_customer_charge(self) -> int:
        return self.captured_total - self.refunded_total

    def active_transfer_total(self) -> int:
        return sum(t["amount"] for t in self.transfers.values() if not t["reversed"])

    def stuck_money(self) -> int:
        return self.captured_total - self.refunded_total - self.active_transfer_total()
