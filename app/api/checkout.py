"""Checkout API routes."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.checkout import get_checkout_service
from app.config import settings

router = APIRouter(prefix="/checkout", tags=["checkout"])


class InitiateRequest(BaseModel):
    product_id: str = Field(..., description="Product the customer buys from Merchant A.")
    customer_id: str | None = None


class ConfirmRequest(BaseModel):
    correlation_id: str
    otp: str


class PayRequest(BaseModel):
    correlation_id: str
    razorpay_payment_id: str
    razorpay_order_id: str
    razorpay_signature: str


class SimulateOptions(BaseModel):
    inventory_fail: bool = False
    capture_fail: bool = False
    transfer_fail: bool = False
    confirmation_timeout: bool = False


class SimulateRequest(BaseModel):
    product_id: str = "a_lap_15biz"
    simulate: SimulateOptions = SimulateOptions()


@router.post("/initiate")
def initiate(req: InitiateRequest) -> dict:
    """Start a purchase from Merchant A; returns the negotiated bundle offer."""
    try:
        return get_checkout_service().initiate(req.product_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/confirm")
def confirm(req: ConfirmRequest) -> dict:
    """OTP human gate -> reserve inventory + create the Razorpay order.

    In real mode returns ``status: awaiting_payment`` with the order_id + key
    for the frontend to open Razorpay Checkout. In mock mode it settles inline.
    """
    try:
        return get_checkout_service().confirm(req.correlation_id, req.otp)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/pay")
def pay(req: PayRequest) -> dict:
    """Verify the Razorpay Checkout signature server-side, then continue the saga."""
    try:
        return get_checkout_service().pay(
            req.correlation_id, req.razorpay_payment_id,
            req.razorpay_order_id, req.razorpay_signature,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/simulate")
def simulate(req: SimulateRequest) -> dict:
    """Run a full checkout with a forced failure (Failure Simulation panel)."""
    return get_checkout_service().simulate(req.product_id, req.simulate.model_dump())


webhook_router = APIRouter(tags=["webhooks"])


@webhook_router.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request) -> dict:
    """Razorpay webhook — server-side source of truth for payment status.

    Verifies the HMAC signature before acting on payment.captured / payment.failed.
    """
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")
    secret = settings.RAZORPAY_WEBHOOK_SECRET

    svc = get_checkout_service()
    # Verify signature when a secret is configured and a real client is in use.
    verifier = getattr(svc._client, "verify_webhook_signature", None)
    if secret and verifier:
        if not verifier(body.decode("utf-8"), signature, secret):
            raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    import json

    try:
        event = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    return svc.handle_webhook(
        event.get("id", ""), event.get("event", ""), event
    )
