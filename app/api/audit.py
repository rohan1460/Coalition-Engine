"""Audit API — the human-readable story of one transaction."""
from fastapi import APIRouter, HTTPException

from app.audit import AuditEvent, get_audit_logger

router = APIRouter(prefix="/audit", tags=["audit"])


def _narrate(event: AuditEvent) -> str:
    """One readable line so a judge can follow the story top-to-bottom."""
    ts = event.timestamp.strftime("%H:%M:%S")
    return (
        f"[{ts}] {event.event_type.value.upper()} · {event.actor}: "
        f"{event.reasoning}"
    )


@router.get("/{correlation_id}")
def get_audit_story(correlation_id: str) -> dict:
    """Return the complete, ordered story of one customer session.

    ``story`` is a readable narrative; ``events`` carries the full structured
    records (inputs, decision, reasoning) for machine consumption.
    """
    events = get_audit_logger().get_story(correlation_id)
    if not events:
        raise HTTPException(
            status_code=404,
            detail=f"No audit events for correlation_id '{correlation_id}'.",
        )
    return {
        "correlation_id": correlation_id,
        "event_count": len(events),
        "story": [_narrate(e) for e in events],
        "events": [e.model_dump(mode="json") for e in events],
    }
