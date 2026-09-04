"""Pre-flight bounds validation for a bundle settlement.

Runs BEFORE any Razorpay API call. The negotiation engine already enforces
these bounds, but money-moving code re-validates independently — defense in
depth. A single failed check rejects the whole settlement.
"""
from dataclasses import dataclass

from app.models import BundleOffer


class BoundsViolation(Exception):
    """Raised when a bundle offer fails one or more safety bounds."""

    def __init__(self, violations: list[str]):
        self.violations = violations
        super().__init__("; ".join(violations))


@dataclass
class SettlementBounds:
    """The independent facts needed to re-verify a split is safe to settle."""

    price_a_inr: int          # merchant A's product list price
    price_b_inr: int          # merchant B's product list price
    min_margin_a_pct: float   # A's negotiated minimum margin floor
    min_margin_b_pct: float   # B's negotiated minimum margin floor


def validate_bounds(
    offer: BundleOffer, bounds: SettlementBounds, cap_inr: int
) -> list[str]:
    """Return a list of human-readable violations ([] means all checks pass)."""
    violations: list[str] = []
    a = offer.merchant_a_amount_inr
    b = offer.merchant_b_amount_inr

    # 1. Splits must reconcile exactly to what the customer pays.
    if a + b != offer.bundle_price_inr:
        violations.append(
            f"split {a}+{b}={a + b} != bundle price {offer.bundle_price_inr}"
        )

    # 2. No negative payouts.
    if a < 0 or b < 0:
        violations.append(f"negative payout (A={a}, B={b})")

    # 3. Each merchant must retain at least its negotiated minimum margin.
    min_a = round(bounds.price_a_inr * bounds.min_margin_a_pct / 100)
    min_b = round(bounds.price_b_inr * bounds.min_margin_b_pct / 100)
    if a < min_a:
        violations.append(
            f"merchant A receives Rs.{a} < min margin Rs.{min_a} "
            f"({bounds.min_margin_a_pct:.0f}% of Rs.{bounds.price_a_inr})"
        )
    if b < min_b:
        violations.append(
            f"merchant B receives Rs.{b} < min margin Rs.{min_b} "
            f"({bounds.min_margin_b_pct:.0f}% of Rs.{bounds.price_b_inr})"
        )

    # 4. Hard per-transaction ceiling.
    if offer.bundle_price_inr > cap_inr:
        violations.append(
            f"bundle price Rs.{offer.bundle_price_inr} exceeds per-transaction "
            f"cap Rs.{cap_inr}"
        )

    return violations
