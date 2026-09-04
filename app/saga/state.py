"""Persisted saga state models.

The saga's entire state — every leg, its reservation/transfer ids, and the
current phase — is a plain serializable object so it can be written to storage
after each transition and reloaded to inspect or resume an interrupted run.
"""
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class SagaStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"                # every leg fulfilled
    PARTIALLY_COMPLETED = "partially_completed"  # some legs degraded/dropped
    COMPENSATED = "compensated"            # rolled back cleanly, no stuck money
    FAILED = "failed"                     # nothing could proceed


class SagaPhase(str, Enum):
    RESERVE = "reserve"
    CAPTURE = "capture"
    TRANSFER = "transfer"
    DONE = "done"


class LegStatus(str, Enum):
    PENDING = "pending"
    RESERVED = "reserved"
    DROPPED = "dropped"          # inventory unavailable -> gracefully excluded
    TRANSFERRED = "transferred"  # fulfilled + settled
    COMPENSATED = "compensated"  # reservation released and/or transfer reversed


class SagaLeg(BaseModel):
    merchant_id: str
    product_id: str
    account: str                 # Razorpay linked account id
    amount_inr: int
    reservation_id: str | None = None
    transfer_id: str | None = None
    reservation_released: bool = False
    transfer_reversed: bool = False
    status: LegStatus = LegStatus.PENDING
    note: str = ""


class SagaState(BaseModel):
    saga_id: str
    correlation_id: str
    bundle_id: str
    status: SagaStatus = SagaStatus.RUNNING
    phase: SagaPhase = SagaPhase.RESERVE
    order_id: str | None = None
    capture_id: str | None = None
    amount_captured_inr: int = 0
    legs: list[SagaLeg] = Field(default_factory=list)
    reason: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def surviving_legs(self) -> list[SagaLeg]:
        """Legs still in play (reserved or already transferred)."""
        return [
            leg for leg in self.legs
            if leg.status in (LegStatus.RESERVED, LegStatus.TRANSFERRED)
        ]

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)
