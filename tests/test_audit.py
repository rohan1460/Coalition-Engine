"""Tests for the audit logger and the /audit/{correlation_id} endpoint."""
from uuid import uuid4

from fastapi.testclient import TestClient

from app.audit import AuditLogger, EventType, get_audit_logger
from app.main import app

client = TestClient(app)


def test_events_persist_and_return_in_order():
    log = AuditLogger(":memory:")
    cid = "sess_test_1"
    log.log(cid, EventType.MATCHING_PERFORMED, "matching_engine",
            reasoning="matched", inputs={"product": "x"})
    log.log(cid, EventType.NEGOTIATION_STARTED, "engine", reasoning="start")
    log.log(cid, EventType.OFFER_PRESENTED, "engine", reasoning="offer",
            decision={"discount_pct": 12})

    story = log.get_story(cid)
    assert [e.event_type for e in story] == [
        EventType.MATCHING_PERFORMED,
        EventType.NEGOTIATION_STARTED,
        EventType.OFFER_PRESENTED,
    ]
    assert [e.seq for e in story] == sorted(e.seq for e in story)
    assert story[0].inputs == {"product": "x"}
    assert story[2].decision == {"discount_pct": 12}
    # correlation isolation
    assert log.get_story("nope") == []


def test_endpoint_returns_story_and_events():
    cid = f"sess_{uuid4().hex[:8]}"
    log = get_audit_logger()  # the endpoint reads this shared logger
    log.log(cid, EventType.NEGOTIATION_STARTED, "engine", reasoning="begin")
    log.log(cid, EventType.OFFER_PRESENTED, "engine", reasoning="12% off")

    resp = client.get(f"/audit/{cid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["correlation_id"] == cid
    assert body["event_count"] == 2
    assert len(body["story"]) == 2
    assert "NEGOTIATION_STARTED" in body["story"][0]
    assert body["events"][0]["reasoning"] == "begin"


def test_endpoint_404_for_unknown_correlation():
    resp = client.get(f"/audit/does_not_exist_{uuid4().hex}")
    assert resp.status_code == 404
