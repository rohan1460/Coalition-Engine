"""API tests for the checkout + health + audit routes."""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_reports_dependencies():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "neo4j" in body["dependencies"]
    assert "razorpay" in body["dependencies"]


def test_initiate_returns_offer():
    resp = client.post("/checkout/initiate", json={"product_id": "a_lap_15biz"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["matched"] is True
    assert body["offer"] is not None
    assert body["offer"]["bundle_price_inr"] > 0
    assert "otp_for_demo" in body


def test_full_checkout_flow_settles_and_is_auditable():
    init = client.post("/checkout/initiate",
                       json={"product_id": "a_lap_15biz"}).json()
    cid, otp = init["correlation_id"], init["otp_for_demo"]

    confirm = client.post("/checkout/confirm",
                          json={"correlation_id": cid, "otp": otp}).json()
    assert confirm["settled"] is True
    assert confirm["status"] in ("completed", "partially_completed")
    assert confirm["stuck_money_inr"] == 0

    story = client.get(f"/audit/{cid}")
    assert story.status_code == 200
    types = [e["event_type"] for e in story.json()["events"]]
    assert "customer_confirmation" in types
    assert "saga_completed" in types


def test_wrong_otp_is_rejected():
    init = client.post("/checkout/initiate",
                       json={"product_id": "a_lap_15biz"}).json()
    confirm = client.post(
        "/checkout/confirm",
        json={"correlation_id": init["correlation_id"], "otp": "000000"},
    ).json()
    assert confirm["settled"] is False
    assert confirm["status"] == "rejected"


def test_confirm_unknown_session_404():
    resp = client.post("/checkout/confirm",
                       json={"correlation_id": "nope", "otp": "123456"})
    assert resp.status_code == 404
