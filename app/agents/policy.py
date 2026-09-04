"""Per-merchant negotiation policy.

A policy is the merchant's general negotiating POSTURE — not its money bounds.
The hard, per-SKU discount ceiling (the thing an agent can never breach) is
derived from actual product economics in economics.py, keyed by product role,
not from a flat per-merchant number here. See economics.py's module docstring
for why: a flat "max 15% off" cannot tell a 10%-margin laptop from a 55%-
margin bag, and that conflation is exactly what produced unrealistic bundle
economics before this policy was split by role.

What's left here is genuinely merchant-level: how eager this merchant is
(stance — shapes the negotiation's opening/pace, never a hard limit) and the
minimum BLENDED bundle discount that makes running this coalition worth the
merchant's while at all (min_viable_discount_pct). If neither side's ceiling
combination can clear the stricter side's viability bar, the deal walks away
— for real, not as a scripted outcome.
"""
from enum import Enum

from pydantic import BaseModel, Field


class Stance(str, Enum):
    AGGRESSIVE = "aggressive"      # opens closer to its ceiling, moves fast
    CONSERVATIVE = "conservative"  # opens cautious, concedes gradually


class MerchantPolicy(BaseModel):
    merchant_id: str

    # Minimum BLENDED bundle discount this merchant considers worth running a
    # coalition for at all. Below this, the deal isn't compelling enough to be
    # worth the integration/acquisition effort — a business threshold, not a
    # margin constraint (that's economics.py's job, per-SKU).
    min_viable_discount_pct: float = Field(default=0.0, ge=0, le=100)

    stance: Stance = Stance.CONSERVATIVE
