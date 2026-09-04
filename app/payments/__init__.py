"""Razorpay Route payment layer with bounds validation + human safety gate."""
from app.payments.bounds import (
    BoundsViolation,
    SettlementBounds,
    validate_bounds,
)
from app.payments.client import (
    MockPaymentClient,
    PaymentClient,
    PaymentConfigError,
    RazorpayClient,
)
from app.payments.service import (
    ConfirmationError,
    PaymentService,
    PendingSettlement,
    SettlementStatus,
)

__all__ = [
    # bounds
    "SettlementBounds",
    "validate_bounds",
    "BoundsViolation",
    # client
    "PaymentClient",
    "RazorpayClient",
    "MockPaymentClient",
    "PaymentConfigError",
    # service
    "PaymentService",
    "PendingSettlement",
    "SettlementStatus",
    "ConfirmationError",
]
