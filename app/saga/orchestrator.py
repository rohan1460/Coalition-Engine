"""Coalition saga orchestrator.

Ordered steps, each with a compensation:
  1. Reserve Merchant A inventory     -> release reservation
  2. Reserve Merchant B inventory     -> release reservation
  3. Capture customer payment         -> refund
  4. Execute Route split transfers    -> reverse transfer

Key behaviours:
  * Inventory failure DEGRADES rather than aborts: the failing merchant's leg is
    dropped and the transaction proceeds for the rest, charging the customer only
    for what can be fulfilled. (Because inventory is reserved BEFORE capture, a
    dropped leg needs no refund — the customer is simply charged less.)
  * Capture failure / unconfirmed offer -> release reservations; nothing charged.
  * Transfer failure -> retry with exponential backoff, then fully compensate
    (reverse any completed transfers, refund the capture, release reservations).
  * Every transition is persisted; every compensation is audit-logged with the
    reason. No terminal state leaves money captured-but-unsettled.

The runner is phase-based and idempotent, so ``resume()`` can pick up an
interrupted saga from its persisted phase.
"""
import logging
import time
from collections.abc import Callable
from uuid import uuid4

from app.audit import AuditLogger, EventType, get_audit_logger
from app.saga.adapter import (
    InventoryError,
    PaymentCaptureError,
    SagaAdapter,
    TransferError,
)
from app.saga.state import (
    LegStatus,
    SagaLeg,
    SagaPhase,
    SagaState,
    SagaStatus,
)
from app.saga.store import SagaStore, get_saga_store

logger = logging.getLogger("saga.orchestrator")


class CoalitionSaga:
    def __init__(
        self,
        adapter: SagaAdapter,
        audit: AuditLogger | None = None,
        store: SagaStore | None = None,
        max_transfer_attempts: int = 3,
        backoff_base_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._adapter = adapter
        self._audit = audit or get_audit_logger()
        self._store = store or get_saga_store()
        self._max_transfer_attempts = max_transfer_attempts
        self._backoff_base = backoff_base_seconds
        self._sleep = sleep

    # -- entry points ------------------------------------------------------

    def run(
        self,
        correlation_id: str,
        bundle_id: str,
        legs: list[SagaLeg],
        order_id: str | None = None,
    ) -> SagaState:
        state = SagaState(
            saga_id=f"saga_{uuid4().hex[:12]}",
            correlation_id=correlation_id,
            bundle_id=bundle_id,
            legs=legs,
            order_id=order_id,
        )
        self._store.save(state)
        self._audit.log(
            correlation_id=correlation_id,
            event_type=EventType.SAGA_STARTED,
            actor="saga",
            reasoning=(
                f"Saga {state.saga_id} started for bundle {bundle_id} with "
                f"{len(legs)} leg(s)."
            ),
            inputs={"saga_id": state.saga_id, "legs": [l.merchant_id for l in legs]},
        )
        return self._run_from(state)

    def resume(self, saga_id: str) -> SagaState:
        state = self._store.load(saga_id)
        if state is None:
            raise KeyError(f"No persisted saga '{saga_id}'.")
        if state.status not in (SagaStatus.RUNNING,):
            # Terminal states are idempotent — nothing to do.
            return state
        self._audit.log(
            correlation_id=state.correlation_id,
            event_type=EventType.SAGA_STARTED,
            actor="saga",
            reasoning=f"Resuming saga {saga_id} from phase '{state.phase.value}'.",
            inputs={"saga_id": saga_id, "phase": state.phase.value},
        )
        return self._run_from(state)

    # -- the phased, idempotent core --------------------------------------

    def _run_from(self, state: SagaState) -> SagaState:
        cid = state.correlation_id

        # Phase 1/2: reserve inventory per leg (degrade on failure).
        if state.phase is SagaPhase.RESERVE:
            for leg in state.legs:
                if leg.status is not LegStatus.PENDING:
                    continue  # idempotent on resume
                try:
                    leg.reservation_id = self._adapter.reserve_inventory(
                        leg.merchant_id, leg.product_id
                    )
                    leg.status = LegStatus.RESERVED
                    self._audit.log(
                        correlation_id=cid,
                        event_type=EventType.SAGA_STEP_COMPLETED,
                        actor="inventory",
                        reasoning=(
                            f"Reserved inventory for {leg.merchant_id} "
                            f"({leg.product_id})."
                        ),
                        inputs={"merchant": leg.merchant_id},
                        decision={"reservation_id": leg.reservation_id},
                    )
                except InventoryError as exc:
                    leg.status = LegStatus.DROPPED
                    leg.note = str(exc)
                    self._audit.log(
                        correlation_id=cid,
                        event_type=EventType.SAGA_STEP_FAILED,
                        actor="inventory",
                        reasoning=(
                            f"Inventory reservation FAILED for {leg.merchant_id}: "
                            f"{exc}. Dropping this leg and continuing so the "
                            f"customer still gets the rest — they won't be charged "
                            f"for the dropped item."
                        ),
                        inputs={"merchant": leg.merchant_id},
                        decision={"dropped": True},
                    )
                self._store.save(state)

            surviving = state.surviving_legs()
            if not surviving:
                state.status = SagaStatus.FAILED
                state.reason = "No inventory could be reserved for any merchant."
                state.phase = SagaPhase.DONE
                self._store.save(state)
                self._audit.log(
                    correlation_id=cid,
                    event_type=EventType.SAGA_FAILED,
                    actor="saga",
                    reasoning=state.reason + " Nothing captured; no money moved.",
                    decision={"status": state.status.value},
                )
                return state

            state.phase = SagaPhase.CAPTURE
            self._store.save(state)

        # Phase 3: confirmation gate + capture.
        if state.phase is SagaPhase.CAPTURE:
            surviving = state.surviving_legs()

            if not self._adapter.is_confirmed():
                return self._compensate_reservations_only(
                    state,
                    reason="Customer did not confirm in time (offer expired).",
                )

            if state.capture_id is None:
                amount = sum(leg.amount_inr for leg in surviving)
                try:
                    state.capture_id = self._adapter.capture_payment(
                        state.order_id, amount
                    )
                    state.amount_captured_inr = amount
                    self._audit.log(
                        correlation_id=cid,
                        event_type=EventType.PAYMENT_INITIATED,
                        actor="payment",
                        reasoning=(
                            f"Captured Rs.{amount} from customer for "
                            f"{len(surviving)} leg(s)."
                        ),
                        decision={"capture_id": state.capture_id,
                                  "amount_inr": amount},
                    )
                except PaymentCaptureError as exc:
                    return self._compensate_reservations_only(
                        state, reason=f"Payment capture failed: {exc}.",
                    )
                self._store.save(state)

            state.phase = SagaPhase.TRANSFER
            self._store.save(state)

        # Phase 4: Route split transfers (retry+backoff, else full compensation).
        if state.phase is SagaPhase.TRANSFER:
            for leg in state.surviving_legs():
                if leg.transfer_id is not None:
                    continue  # idempotent on resume
                try:
                    leg.transfer_id = self._transfer_with_retry(leg, cid)
                    leg.status = LegStatus.TRANSFERRED
                    self._audit.log(
                        correlation_id=cid,
                        event_type=EventType.SPLIT_EXECUTED,
                        actor="payment",
                        reasoning=(
                            f"Transferred Rs.{leg.amount_inr} to {leg.merchant_id} "
                            f"({leg.account})."
                        ),
                        decision={"transfer_id": leg.transfer_id},
                    )
                    self._store.save(state)
                except TransferError as exc:
                    return self._compensate_full(
                        state,
                        reason=(
                            f"Transfer to {leg.merchant_id} failed after "
                            f"{self._max_transfer_attempts} attempts: {exc}."
                        ),
                    )

            dropped = any(leg.status is LegStatus.DROPPED for leg in state.legs)
            state.status = (
                SagaStatus.PARTIALLY_COMPLETED if dropped else SagaStatus.COMPLETED
            )
            state.phase = SagaPhase.DONE
            self._store.save(state)
            self._audit.log(
                correlation_id=cid,
                event_type=EventType.SAGA_COMPLETED,
                actor="saga",
                reasoning=(
                    f"Saga {state.saga_id} {state.status.value}: "
                    f"Rs.{state.amount_captured_inr} captured and split; "
                    + ("one leg was dropped." if dropped else "all legs fulfilled.")
                ),
                decision={"status": state.status.value},
            )

        return state

    # -- retry -------------------------------------------------------------

    def _transfer_with_retry(self, leg: SagaLeg, cid: str) -> str:
        last: Exception | None = None
        for attempt in range(1, self._max_transfer_attempts + 1):
            try:
                return self._adapter.execute_transfer(leg.account, leg.amount_inr)
            except TransferError as exc:
                last = exc
                if attempt < self._max_transfer_attempts:
                    delay = self._backoff_base * (2 ** (attempt - 1))
                    self._audit.log(
                        correlation_id=cid,
                        event_type=EventType.SAGA_STEP_FAILED,
                        actor="payment",
                        reasoning=(
                            f"Transfer to {leg.merchant_id} attempt "
                            f"{attempt}/{self._max_transfer_attempts} failed: {exc}. "
                            f"Backing off {delay:.2f}s and retrying."
                        ),
                        inputs={"account": leg.account, "attempt": attempt},
                    )
                    self._sleep(delay)
        assert last is not None
        raise last

    # -- compensations -----------------------------------------------------

    def _compensate_reservations_only(
        self, state: SagaState, reason: str
    ) -> SagaState:
        """Release reservations; nothing was captured, so no refund needed."""
        for leg in state.legs:
            if leg.reservation_id and not leg.reservation_released:
                self._adapter.release_inventory(leg.reservation_id)
                leg.reservation_released = True
                leg.status = LegStatus.COMPENSATED
                self._audit.log(
                    correlation_id=state.correlation_id,
                    event_type=EventType.COMPENSATION_EXECUTED,
                    actor="inventory",
                    reasoning=(
                        f"Released reservation for {leg.merchant_id}. Reason: {reason}"
                    ),
                    decision={"reservation_id": leg.reservation_id},
                )
        state.status = SagaStatus.COMPENSATED
        state.reason = reason
        state.phase = SagaPhase.DONE
        self._store.save(state)
        self._audit.log(
            correlation_id=state.correlation_id,
            event_type=EventType.SAGA_FAILED,
            actor="saga",
            reasoning=(
                f"Saga {state.saga_id} compensated (no capture). {reason} "
                f"No money was moved."
            ),
            decision={"status": state.status.value, "net_charge_inr": 0},
        )
        return state

    def _compensate_full(self, state: SagaState, reason: str) -> SagaState:
        """Reverse transfers, refund the capture, release reservations."""
        # 1. reverse any transfers already done (reverse order of completion)
        for leg in state.legs:
            if leg.transfer_id and not leg.transfer_reversed:
                self._adapter.reverse_transfer(leg.transfer_id)
                leg.transfer_reversed = True
                self._audit.log(
                    correlation_id=state.correlation_id,
                    event_type=EventType.COMPENSATION_EXECUTED,
                    actor="payment",
                    reasoning=(
                        f"Reversed transfer to {leg.merchant_id}. Reason: {reason}"
                    ),
                    decision={"transfer_id": leg.transfer_id},
                )

        # 2. refund the captured payment in full
        if state.capture_id and state.amount_captured_inr > 0:
            self._adapter.refund_payment(state.capture_id, state.amount_captured_inr)
            self._audit.log(
                correlation_id=state.correlation_id,
                event_type=EventType.COMPENSATION_EXECUTED,
                actor="payment",
                reasoning=(
                    f"Refunded Rs.{state.amount_captured_inr} to customer. "
                    f"Reason: {reason}"
                ),
                decision={"refund_inr": state.amount_captured_inr},
            )

        # 3. release inventory reservations
        for leg in state.legs:
            if leg.reservation_id and not leg.reservation_released:
                self._adapter.release_inventory(leg.reservation_id)
                leg.reservation_released = True
                self._audit.log(
                    correlation_id=state.correlation_id,
                    event_type=EventType.COMPENSATION_EXECUTED,
                    actor="inventory",
                    reasoning=(
                        f"Released reservation for {leg.merchant_id}. Reason: {reason}"
                    ),
                    decision={"reservation_id": leg.reservation_id},
                )
            if leg.status is not LegStatus.DROPPED:
                leg.status = LegStatus.COMPENSATED

        state.status = SagaStatus.COMPENSATED
        state.reason = reason
        state.phase = SagaPhase.DONE
        self._store.save(state)
        self._audit.log(
            correlation_id=state.correlation_id,
            event_type=EventType.SAGA_FAILED,
            actor="saga",
            reasoning=(
                f"Saga {state.saga_id} fully compensated. {reason} "
                f"Customer refunded in full; no money left in a stuck state."
            ),
            decision={"status": state.status.value, "net_charge_inr": 0},
        )
        return state
