"""Deterministic per-SKU margin economics.

This module is the ENTIRE source of truth for how much any given product can
be discounted in a coalition deal. It replaces a flat, merchant-level
"max_discount_pct" with a number derived from that SKU's actual unit
economics — because a flat percentage cannot tell the difference between a
laptop with a 10% margin and a bag with a 55% margin, and treating them the
same is how you end up selling a laptop below cost.

THE MODEL
---------
Every product has a role:
  * "anchor"    — the high-value item driving the purchase. Retail margins on
                  this category are thin (competitive market), so the seller
                  protects almost all of it even in a promotional bundle.
  * "companion" — the attach item riding the anchor's traffic. Margins here
                  are fat (classic accessory economics), so the seller can
                  give away most of it and still profit handsomely.

For a given SKU:
    margin_pct           = (price - cost) / price * 100        [what they earn]
    discount_ceiling_pct  = margin_pct * (1 - retention_fraction)
                            clamped into [role.min_ceiling, role.max_ceiling]
                            and never allowed to exceed margin_pct itself
                            (a merchant never sells below cost, full stop)
    margin_floor_pct      = margin_pct - discount_ceiling_pct   [the hard wall]

``retention_fraction`` is "how much of my own margin I insist on keeping even
in a coalition deal" — high for anchors (they're not desperate; they'd have
made the sale anyway), low for companions (a new customer is worth a lot of
sacrificed margin). This is what makes Merchant B contribute proportionally
more of the discount COST without ever touching product price directly — the
weighting comes from margin economics, not sticker price.

Every number here is plain arithmetic. No LLM, no external call, no
randomness — an agent's ceiling for a SKU is 100% reproducible from
(price, cost, role).
"""
from dataclasses import dataclass

from app.models.product import ProductRole


@dataclass(frozen=True)
class RoleEconomics:
    # Fraction of NATURAL margin the merchant insists on keeping even in a
    # coalition deal. 0.82 => will give away at most 18% of its margin.
    retention_fraction: float
    min_ceiling_pct: float   # discount ceiling never goes below this
    max_ceiling_pct: float   # discount ceiling never goes above this


# Anchor: thin, competitive margins (7-12% typical for durable electronics).
# Retaining 82% of that margin leaves a realistic 1-3% discount ceiling.
# Companion: fat accessory-category margins (40-60% typical). Retaining only
# 35% of that leaves 20-40% of headroom — real "clearance sale" territory.
ROLE_ECONOMICS: dict[ProductRole, RoleEconomics] = {
    "anchor": RoleEconomics(
        retention_fraction=0.82, min_ceiling_pct=1.0, max_ceiling_pct=3.0
    ),
    "companion": RoleEconomics(
        retention_fraction=0.35, min_ceiling_pct=20.0, max_ceiling_pct=40.0
    ),
}


@dataclass(frozen=True)
class SkuFloor:
    """The negotiable envelope for ONE product, derived from its economics."""

    role: ProductRole
    margin_pct: float            # natural retail margin
    discount_ceiling_pct: float  # the most this merchant will ever discount it
    margin_floor_pct: float      # margin_pct - discount_ceiling_pct; the hard wall


def compute_sku_floor(
    price_inr: int, cost_price_inr: int, role: ProductRole
) -> SkuFloor:
    """Derive a SKU's discount ceiling from its real margin. Pure arithmetic."""
    if price_inr <= 0:
        raise ValueError("price_inr must be positive")
    if cost_price_inr > price_inr:
        raise ValueError(
            f"cost_price_inr ({cost_price_inr}) cannot exceed price_inr "
            f"({price_inr})."
        )

    margin_pct = (price_inr - cost_price_inr) / price_inr * 100
    econ = ROLE_ECONOMICS[role]

    raw_ceiling = margin_pct * (1 - econ.retention_fraction)
    ceiling = min(econ.max_ceiling_pct, max(econ.min_ceiling_pct, raw_ceiling))
    # Never let a role's minimum-ceiling floor push a paper-thin-margin SKU
    # into selling below cost — the ceiling can never exceed the margin itself.
    ceiling = min(ceiling, margin_pct)

    return SkuFloor(
        role=role,
        margin_pct=round(margin_pct, 4),
        discount_ceiling_pct=round(ceiling, 4),
        margin_floor_pct=round(margin_pct - ceiling, 4),
    )
