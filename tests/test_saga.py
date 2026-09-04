"""Saga failure-mode tests.

Each test deliberately triggers one failure and asserts the saga degrades
gracefully with NO money left in a stuck state (adapter.stuck_money() == 0).
"""
from app.audit import AuditLogger, EventType
from app.saga import (
    CoalitionSaga,
    LegStatus,
    MockSagaAdapter,
    SagaLeg,
    SagaPhase,
    SagaState,
    SagaStatus,
    SagaStore,
)

CID = "sess_saga_test"
# Laptop leg Rs.72000 -> acc_A; bag leg Rs.4000 -> acc_B. Bundle Rs.76000.
LEG_A = dict(merchant_id="ma", product_id="a_lap_15biz", account="acc_A",
             amount_inr=72000)
LEG_B = dict(merchant_id="mb", product_id="b_bag_15backpack", account="acc_B",
             amount_inr=4000)


def _legs():
    return [SagaLeg(**LEG_A), SagaLeg(**LEG_B)]


def _saga(adapter):
    return CoalitionSaga(
        adapter,
        audit=AuditLogger(":memory:"),
        store=SagaStore(":memory:"),
        max_transfer_attempts=3,
        backoff_base_seconds=0.01,
        sleep=lambda _s: None,   # no real waiting in tests
    )


def _has(saga, event_type) -> bool:
    return any(
        e.event_type is event_type for e in saga._audit.get_story(CID)
    )


# -- happy path -------------------------------------------------------------

def test_happy_path_completes_with_no_stuck_money():
    adapter = MockSagaAdapter()
    state = _saga(adapter).run(CID, "bnd", _legs())
    assert state.status is SagaStatus.COMPLETED
    assert adapter.net_customer_charge() == 76000
    assert adapter.stuck_money() == 0


# -- failure 1: inventory lock (graceful degradation) -----------------------

def test_inventory_lock_failure_degrades_to_single_merchant():
    # Merchant B's inventory lock fails.
    adapter = MockSagaAdapter(fail_inventory_for={"mb"})
    state = _saga(adapter).run(CID, "bnd", _legs())

    assert state.status is SagaStatus.PARTIALLY_COMPLETED
    leg_a = next(l for l in state.legs if l.merchant_id == "ma")
    leg_b = next(l for l in state.legs if l.merchant_id == "mb")
    assert leg_a.status is LegStatus.TRANSFERRED     # laptop fulfilled
    assert leg_b.status is LegStatus.DROPPED          # bag dropped

    # Customer charged ONLY for the laptop, not the bag. Nothing stuck.
    assert adapter.net_customer_charge() == 72000
    assert adapter.stuck_money() == 0


def test_all_inventory_failure_charges_nothing():
    adapter = MockSagaAdapter(fail_inventory_for={"ma", "mb"})
    state = _saga(adapter).run(CID, "bnd", _legs())
    assert state.status is SagaStatus.FAILED
    assert adapter.net_customer_charge() == 0
    assert adapter.stuck_money() == 0


# -- failure 2: Route transfer (retry then compensate) ----------------------

def test_route_transfer_failure_retries_then_refunds():
    # Every transfer to acc_B fails -> after retries, full compensation.
    adapter = MockSagaAdapter(fail_transfer_for={"acc_B"})
    saga = _saga(adapter)
    state = saga.run(CID, "bnd", _legs())

    assert state.status is SagaStatus.COMPENSATED
    # It retried the failing transfer the configured number of times.
    assert adapter.transfer_attempts["acc_B"] == 3
    # Customer fully refunded; the succeeded transfer (A) was reversed.
    assert adapter.net_customer_charge() == 0
    assert adapter.active_transfer_total() == 0
    assert adapter.stuck_money() == 0
    assert adapter.outstanding_reservations() == 0
    assert _has(saga, EventType.COMPENSATION_EXECUTED)


def test_route_transfer_recovers_within_retries():
    # Fails twice then succeeds — the backoff retry should save it.
    adapter = MockSagaAdapter(fail_transfer_for={"acc_B"}, transfer_fail_times=2)
    state = _saga(adapter).run(CID, "bnd", _legs())
    assert state.status is SagaStatus.COMPLETED
    assert adapter.transfer_attempts["acc_B"] == 3   # 2 fails + 1 success
    assert adapter.net_customer_charge() == 76000
    assert adapter.stuck_money() == 0


# -- failure 3: payment capture --------------------------------------------

def test_payment_capture_failure_releases_reservations():
    adapter = MockSagaAdapter(fail_capture=True)
    state = _saga(adapter).run(CID, "bnd", _legs())
    assert state.status is SagaStatus.COMPENSATED
    assert adapter.net_customer_charge() == 0            # nothing captured
    assert adapter.outstanding_reservations() == 0       # both released
    assert adapter.stuck_money() == 0


# -- failure 4: confirmation timeout ---------------------------------------

def test_confirmation_timeout_releases_reservations():
    adapter = MockSagaAdapter(confirmed=False)
    saga = _saga(adapter)
    state = saga.run(CID, "bnd", _legs())
    assert state.status is SagaStatus.COMPENSATED
    assert adapter.net_customer_charge() == 0            # never captured
    assert adapter.outstanding_reservations() == 0
    assert adapter.stuck_money() == 0
    assert _has(saga, EventType.COMPENSATION_EXECUTED)


# -- persistence + resume ---------------------------------------------------

def test_state_is_persisted_and_inspectable():
    adapter = MockSagaAdapter()
    saga = _saga(adapter)
    state = saga.run(CID, "bnd", _legs())
    reloaded = saga._store.load(state.saga_id)
    assert reloaded is not None
    assert reloaded.status is SagaStatus.COMPLETED
    assert reloaded.saga_id == state.saga_id


def test_interrupted_saga_resumes_and_completes():
    # Simulate a crash AFTER capture but BEFORE transfers: a persisted state at
    # the TRANSFER phase with reservations + capture done, no transfers yet.
    adapter = MockSagaAdapter()
    # The pre-crash process had already captured payment; reflect that in the
    # ledger so the money math is consistent after resume.
    adapter.captured_total = 76000
    saga = _saga(adapter)
    interrupted = SagaState(
        saga_id="saga_interrupted",
        correlation_id=CID,
        bundle_id="bnd",
        status=SagaStatus.RUNNING,
        phase=SagaPhase.TRANSFER,
        capture_id="cap_prior",
        amount_captured_inr=76000,
        legs=[
            SagaLeg(**LEG_A, reservation_id="resv_1", status=LegStatus.RESERVED),
            SagaLeg(**LEG_B, reservation_id="resv_2", status=LegStatus.RESERVED),
        ],
    )
    saga._store.save(interrupted)

    resumed = saga.resume("saga_interrupted")
    assert resumed.status is SagaStatus.COMPLETED
    # Only the transfers ran on resume (2 transfers, no re-capture).
    assert len(adapter.transfers) == 2
    assert adapter.stuck_money() == 0
