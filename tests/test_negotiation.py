"""Tests for the deterministic margin economics and the bounded negotiation."""
from app.agents import (
    MerchantAgent,
    MerchantPolicy,
    NegotiationContext,
    NegotiationEngine,
    Stance,
    compute_split,
    new_negotiation_id,
)
from app.audit import AuditLogger
from app.models import BundleStatus, Product

# Anchor: 15" business laptop, ~10.0% natural margin (price 84999, cost 76499
# -> margin floor lands at exactly 8.2%, same numbers as the real catalog).
ANCHOR = Product(
    product_id="pa", merchant_id="ma", name="Laptop", description="d",
    category="Laptops", price_inr=84999, cost_price_inr=76499,
    product_role="anchor", stock_qty=5, tags=[],
)
# Companion: laptop sleeve, ~55% natural margin -> generous discount ceiling.
COMPANION = Product(
    product_id="pb", merchant_id="mb", name="Sleeve", description="d",
    category="Sleeves", price_inr=1299, cost_price_inr=585,
    product_role="companion", stock_qty=5, tags=[],
)
# A second anchor with a much thinner margin, paired with a low-value
# companion — structurally cannot fund a viable blended discount.
THIN_ANCHOR = Product(
    product_id="pa2", merchant_id="ma", name="Gaming Laptop", description="d",
    category="Laptops", price_inr=149999, cost_price_inr=140999,
    product_role="anchor", stock_qty=5, tags=[],
)
CHEAP_COMPANION = Product(
    product_id="pb2", merchant_id="mb", name="Cable Roll", description="d",
    category="Organizers", price_inr=699, cost_price_inr=266,
    product_role="companion", stock_qty=5, tags=[],
)


def _ctx(a: Product, b: Product):
    return NegotiationContext(
        negotiation_id=new_negotiation_id(),
        product_a_id=a.product_id, product_b_id=b.product_id,
        merchant_a_id=a.merchant_id, merchant_b_id=b.merchant_id,
        price_a_inr=a.price_inr, price_b_inr=b.price_inr,
        cost_a_inr=a.cost_price_inr, cost_b_inr=b.cost_price_inr,
        role_a=a.product_role, role_b=b.product_role,
        affinity_score=0.5,
    )


def _agents(min_viable_a=1.0, min_viable_b=2.0):
    a = MerchantAgent(MerchantPolicy(
        merchant_id="ma", min_viable_discount_pct=min_viable_a,
        stance=Stance.AGGRESSIVE))
    b = MerchantAgent(MerchantPolicy(
        merchant_id="mb", min_viable_discount_pct=min_viable_b,
        stance=Stance.CONSERVATIVE))
    return a, b


def test_compute_split_reconciles():
    p = compute_split(80000, 4000, discount_pct_a=5.0, discount_pct_b=20.0)
    assert p.a_concession_inr == 4000        # 5% of 80000
    assert p.b_concession_inr == 800         # 20% of 4000
    assert p.merchant_a_amount_inr + p.merchant_b_amount_inr == p.bundle_price_inr
    assert p.bundle_price_inr == 84000 - 4800
    assert round(p.discount_pct, 2) == round(4800 / 84000 * 100, 2)


def test_compute_split_clamps_negative_discount():
    # A "discount" can never be negative.
    p = compute_split(80000, 4000, discount_pct_a=-5.0, discount_pct_b=10.0)
    assert p.a_concession_inr == 0
    assert p.b_concession_inr == 400


def test_anchor_ceiling_is_tight_companion_ceiling_is_generous():
    ctx = _ctx(ANCHOR, COMPANION)
    # Matches the worked example: ~10% margin, 82% retained -> ~1.8% ceiling,
    # ~8.2% margin floor.
    assert 1.5 <= ctx.sku_a.discount_ceiling_pct <= 2.0
    assert round(ctx.sku_a.margin_floor_pct, 1) == 8.2
    # ~55% margin, 35% retained -> ceiling in the 20-40% band.
    assert 20.0 <= ctx.sku_b.discount_ceiling_pct <= 40.0


def test_negotiation_converges_with_realistic_margins():
    a, b = _agents()
    engine = NegotiationEngine(a, b, AuditLogger(":memory:"), max_rounds=5)
    result = engine.negotiate(_ctx(ANCHOR, COMPANION), ANCHOR, COMPANION)

    assert result.status is BundleStatus.AGREED
    bundle = result.bundle
    assert bundle is not None
    # Split must reconcile.
    assert bundle.merchant_a_amount_inr + bundle.merchant_b_amount_inr == bundle.bundle_price_inr
    # Realistic, not the old flat-12%-off-everything behaviour: anchor barely
    # moves, companion carries almost all of the discount, blended is small.
    assert bundle.merchant_a_discount_pct <= 3.0
    assert bundle.merchant_b_discount_pct >= 20.0
    assert 2.0 <= bundle.discount_pct <= 5.0
    # Neither side ever sold below its own margin floor.
    ctx = _ctx(ANCHOR, COMPANION)
    min_a = round(ANCHOR.price_inr * ctx.sku_a.margin_floor_pct / 100)
    min_b = round(COMPANION.price_inr * ctx.sku_b.margin_floor_pct / 100)
    assert bundle.merchant_a_amount_inr >= min_a
    assert bundle.merchant_b_amount_inr >= min_b


def test_negotiation_walks_away_when_ceilings_cannot_fund_viability():
    # Thin-margin anchor (gaming laptop) dominates the total so heavily that
    # even both sides maxed out can't clear the 2% viability bar.
    a, b = _agents()
    engine = NegotiationEngine(a, b, AuditLogger(":memory:"), max_rounds=5)
    result = engine.negotiate(_ctx(THIN_ANCHOR, CHEAP_COMPANION),
                              THIN_ANCHOR, CHEAP_COMPANION)

    assert result.status is BundleStatus.REJECTED
    assert result.bundle is None            # no fabricated fallback deal
    assert result.offer_copy is None
    assert result.rounds_used == 5          # ran the full cap, genuinely stuck


def test_every_round_is_audited_with_specific_reasoning():
    a, b = _agents()
    audit = AuditLogger(":memory:")
    nid = new_negotiation_id()
    ctx = NegotiationContext(
        negotiation_id=nid, product_a_id="pa", product_b_id="pb",
        merchant_a_id="ma", merchant_b_id="mb",
        price_a_inr=ANCHOR.price_inr, price_b_inr=COMPANION.price_inr,
        cost_a_inr=ANCHOR.cost_price_inr, cost_b_inr=COMPANION.cost_price_inr,
        role_a="anchor", role_b="companion",
        affinity_score=0.5, correlation_id=nid,
    )
    NegotiationEngine(a, b, audit, max_rounds=5).negotiate(ctx, ANCHOR, COMPANION)

    events = audit.get_story(nid)
    types = [e.event_type.value for e in events]
    assert "negotiation_started" in types
    assert "negotiation_round" in types
    assert "offer_presented" in types
    assert [e.seq for e in events] == sorted(e.seq for e in events)
    # Every event carries reasoning (the WHY) — the graded requirement.
    assert all(e.reasoning for e in events)
    # Reasoning cites the ACTUAL constraint, not a generic "agreed on X%".
    round_events = [e for e in events if e.event_type.value == "negotiation_round"]
    assert any("margin floor" in e.reasoning for e in round_events)
