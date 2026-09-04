"""Structured, persistent audit trail.

Every consequential action across a customer session is recorded as an
immutable JSON event tying together *what* happened, *who* did it, the *inputs*
they saw, the *decision* they made, and the *reasoning* WHY. All events from one
customer session share a ``correlation_id`` so the complete story can be
reconstructed in order.

Events are persisted to SQLite so the log survives process restarts. The table
is append-only — we insert, never update or delete — which is exactly what an
audit trail should guarantee.
"""
import json
import logging
import sqlite3
import threading
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger("audit")

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "audit.db"


class EventType(str, Enum):
    """The lifecycle events we capture across a coalition transaction."""

    MATCHING_PERFORMED = "matching_performed"
    AFFINITY_SCORED = "affinity_scored"
    NEGOTIATION_STARTED = "negotiation_started"
    NEGOTIATION_ROUND = "negotiation_round"
    OFFER_PRESENTED = "offer_presented"
    NEGOTIATION_FAILED = "negotiation_failed"
    CUSTOMER_CONFIRMATION = "customer_confirmation"
    PAYMENT_INITIATED = "payment_initiated"
    SPLIT_EXECUTED = "split_executed"
    FAILURE = "failure"
    ROLLBACK = "rollback"
    # Saga lifecycle
    SAGA_STARTED = "saga_started"
    SAGA_STEP_COMPLETED = "saga_step_completed"
    SAGA_STEP_FAILED = "saga_step_failed"
    COMPENSATION_EXECUTED = "compensation_executed"
    SAGA_COMPLETED = "saga_completed"
    SAGA_FAILED = "saga_failed"


class AuditEvent(BaseModel):
    seq: int = Field(..., description="Global insertion order (monotonic).")
    event_id: str
    timestamp: datetime
    correlation_id: str = Field(..., description="Ties one customer session.")
    event_type: EventType
    actor: str = Field(..., description="Which agent/system acted.")
    inputs: dict = Field(default_factory=dict, description="What the actor saw.")
    decision: dict = Field(default_factory=dict, description="What it decided.")
    reasoning: str = Field(default="", description="WHY — the explainability.")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id       TEXT NOT NULL,
    timestamp      TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    event_type     TEXT NOT NULL,
    actor          TEXT NOT NULL,
    inputs         TEXT NOT NULL,
    decision       TEXT NOT NULL,
    reasoning      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_correlation
    ON audit_events (correlation_id, seq);
"""


class AuditLogger:
    """SQLite-backed append-only audit log.

    Pass ``":memory:"`` for an ephemeral in-process log (tests); pass a path to
    persist. Defaults to ``data/audit.db``.
    """

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = DEFAULT_DB_PATH
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            db_path = str(db_path)

        self._lock = threading.Lock()
        # check_same_thread=False so the FastAPI threadpool can read/write.
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def log(
        self,
        correlation_id: str,
        event_type: EventType,
        actor: str,
        reasoning: str = "",
        inputs: dict | None = None,
        decision: dict | None = None,
    ) -> AuditEvent:
        event_id = str(uuid4())
        ts = datetime.now(timezone.utc)
        inputs = inputs or {}
        decision = decision or {}

        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO audit_events "
                "(event_id, timestamp, correlation_id, event_type, actor, "
                " inputs, decision, reasoning) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event_id,
                    ts.isoformat(),
                    correlation_id,
                    event_type.value,
                    actor,
                    json.dumps(inputs, default=str),
                    json.dumps(decision, default=str),
                    reasoning,
                ),
            )
            seq = cur.lastrowid

        logger.info(
            "#%d [%s] %s (%s) — %s",
            seq, correlation_id, event_type.value, actor, reasoning,
        )
        return AuditEvent(
            seq=seq,
            event_id=event_id,
            timestamp=ts,
            correlation_id=correlation_id,
            event_type=event_type,
            actor=actor,
            inputs=inputs,
            decision=decision,
            reasoning=reasoning,
        )

    def get_story(self, correlation_id: str) -> list[AuditEvent]:
        """Return the complete, ordered event story for one session."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM audit_events WHERE correlation_id = ? "
                "ORDER BY seq ASC",
                (correlation_id,),
            ).fetchall()
        return [self._row_to_event(r) for r in rows]

    def correlation_ids(self) -> list[str]:
        """All known session ids, most recent first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT correlation_id, MAX(seq) AS last FROM audit_events "
                "GROUP BY correlation_id ORDER BY last DESC"
            ).fetchall()
        return [r["correlation_id"] for r in rows]

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_event(row: sqlite3.Row) -> AuditEvent:
        return AuditEvent(
            seq=row["seq"],
            event_id=row["event_id"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            correlation_id=row["correlation_id"],
            event_type=EventType(row["event_type"]),
            actor=row["actor"],
            inputs=json.loads(row["inputs"]),
            decision=json.loads(row["decision"]),
            reasoning=row["reasoning"],
        )


# Shared persistent logger (writes to data/audit.db).
_audit_logger: AuditLogger | None = None


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger
