"""SQLite persistence for saga state.

Every transition is upserted here, so an interrupted saga survives a restart and
can be inspected or resumed. Like the audit log, this is append-friendly and
keyed for fast lookup by saga_id.
"""
import logging
import sqlite3
import threading
from pathlib import Path

from app.saga.state import SagaState

logger = logging.getLogger("saga.store")

DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "saga.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS saga_states (
    saga_id        TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    status         TEXT NOT NULL,
    phase          TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    state_json     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_saga_correlation ON saga_states (correlation_id);
"""


class SagaStore:
    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = DEFAULT_DB_PATH
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            db_path = str(db_path)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(_SCHEMA)

    def save(self, state: SagaState) -> None:
        state.touch()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO saga_states "
                "(saga_id, correlation_id, status, phase, updated_at, state_json) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(saga_id) DO UPDATE SET "
                "  status=excluded.status, phase=excluded.phase, "
                "  updated_at=excluded.updated_at, state_json=excluded.state_json",
                (
                    state.saga_id,
                    state.correlation_id,
                    state.status.value,
                    state.phase.value,
                    state.updated_at.isoformat(),
                    state.model_dump_json(),
                ),
            )

    def load(self, saga_id: str) -> SagaState | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT state_json FROM saga_states WHERE saga_id = ?",
                (saga_id,),
            ).fetchone()
        return SagaState.model_validate_json(row["state_json"]) if row else None

    def list_by_correlation(self, correlation_id: str) -> list[SagaState]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT state_json FROM saga_states WHERE correlation_id = ? "
                "ORDER BY updated_at ASC",
                (correlation_id,),
            ).fetchall()
        return [SagaState.model_validate_json(r["state_json"]) for r in rows]

    def close(self) -> None:
        self._conn.close()


_saga_store: SagaStore | None = None


def get_saga_store() -> SagaStore:
    global _saga_store
    if _saga_store is None:
        _saga_store = SagaStore()
    return _saga_store
