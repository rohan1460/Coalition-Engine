"""Saga action adapter — the seam between orchestration and the real world.

The orchestrator calls this interface for each step and its compensation. In
production a real adapter wires these to an inventory service + the Route
PaymentService. For tests and local demos, ``MockSagaAdapter`` simulates the
world and can be told to fail any specific step, while tracking a money ledger
so we can prove no funds are ever left stuck.
"""
import logging
from typing import Protocol, runtime_checkable

logger = logging.getLogger("saga.adapter")


class InventoryError(Exception):
    """Inventory could not be reserved."""


class PaymentCaptureError(Exception):
    """Customer payment could not be captured."""


class TransferError(Exception):
    """A Route split transfer failed."""


@runtime_checkable
class SagaAdapter(Protocol):
    def reserve_inventory(self, merchant_id: str, product_id: str) -> str: ...
    def release_inventory(self, reservation_id: str) -> None: ...
    def is_confirmed(self) -> bool: ...
    def capture_payment(self, order_id: str | None, amount_inr: int) -> str: ...
    def refund_payment(self, capture_id: str, amount_inr: int) -> None: ...
    def execute_transfer(self, account: str, amount_inr: int) -> str: ...
    def reverse_transfer(self, transfer_id: str) -> None: ...


class MockSagaAdapter:
    """Simulated world with injectable failures and a money ledger."""

    def __init__(
        self,
        *,
        fail_inventory_for: set[str] | None = None,
        confirmed: bool = True,
        fail_capture: bool = False,
        fail_transfer_for: set[str] | None = None,
        transfer_fail_times: int = 10 ** 9,  # per-account attempts that fail
    ):
        self.fail_inventory_for = fail_inventory_for or set()
        self.confirmed = confirmed
        self.fail_capture = fail_capture
        self.fail_transfer_for = fail_transfer_for or set()
        self.transfer_fail_times = transfer_fail_times

        # Ledger / bookkeeping.
        self.reservations: dict[str, dict] = {}
        self.captured_total = 0
        self.refunded_total = 0
        self.transfers: dict[str, dict] = {}
        self.transfer_attempts: dict[str, int] = {}
        self._counter = 0

    def _next(self, prefix: str) -> str:
        self._counter += 1
        return f"{prefix}_{self._counter:06d}"

    # -- inventory ---------------------------------------------------------

    def reserve_inventory(self, merchant_id: str, product_id: str) -> str:
        if merchant_id in self.fail_inventory_for:
            raise InventoryError(
                f"{merchant_id}: '{product_id}' out of stock / lock failed"
            )
        rid = self._next("resv")
        self.reservations[rid] = {"merchant_id": merchant_id, "released": False}
        return rid

    def release_inventory(self, reservation_id: str) -> None:
        if reservation_id in self.reservations:
            self.reservations[reservation_id]["released"] = True

    # -- confirmation gate -------------------------------------------------

    def is_confirmed(self) -> bool:
        return self.confirmed

    # -- payment -----------------------------------------------------------

    def capture_payment(self, order_id: str | None, amount_inr: int) -> str:
        if self.fail_capture:
            raise PaymentCaptureError("gateway declined capture")
        self.captured_total += amount_inr
        return self._next("cap")

    def refund_payment(self, capture_id: str, amount_inr: int) -> None:
        self.refunded_total += amount_inr

    # -- transfers ---------------------------------------------------------

    def execute_transfer(self, account: str, amount_inr: int) -> str:
        self.transfer_attempts[account] = self.transfer_attempts.get(account, 0) + 1
        if (
            account in self.fail_transfer_for
            and self.transfer_attempts[account] <= self.transfer_fail_times
        ):
            raise TransferError(f"transfer to {account} failed (Route unavailable)")
        tid = self._next("trf")
        self.transfers[tid] = {"account": account, "amount": amount_inr,
                               "reversed": False}
        return tid

    def reverse_transfer(self, transfer_id: str) -> None:
        if transfer_id in self.transfers:
            self.transfers[transfer_id]["reversed"] = True

    # -- ledger assertions (for tests) ------------------------------------

    def net_customer_charge(self) -> int:
        return self.captured_total - self.refunded_total

    def active_transfer_total(self) -> int:
        return sum(t["amount"] for t in self.transfers.values() if not t["reversed"])

    def stuck_money(self) -> int:
        """Money captured but neither settled to a merchant nor refunded.

        Must be zero at every terminal state — that's the whole point.
        """
        return self.captured_total - self.refunded_total - self.active_transfer_total()

    def outstanding_reservations(self) -> int:
        return sum(1 for r in self.reservations.values() if not r["released"])
