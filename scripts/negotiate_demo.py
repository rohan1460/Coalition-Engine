"""Demonstrate the agent negotiation protocol end-to-end with REAL margins.

Both scenarios use the SAME production merchant policies (app/checkout/
service.py's _POLICIES) — no per-scenario overrides. The outcome (converge vs
walk away) is decided purely by each product pairing's real margin economics.

  1. LumenBook Pro 15 (anchor, ~10% margin) + Slim 13 Sleeve (companion, ~55%
     margin) -> converges. The anchor barely moves; the companion carries the
     discount; the blended total lands in the realistic 2-5% band.
  2. LumenBook Predator 16 Gaming Laptop (anchor, ~6% margin, dominates the
     total) + Cable Management Roll (cheap companion) -> even both sides at
     FULL ceiling can't clear the coalition's viability bar. Clean walk-away,
     no fabricated fallback deal.

Every round is printed straight from the audit trail.

Run:
    python -m scripts.negotiate_demo
"""
import logging

from app.agents import (
    MerchantAgent,
    MerchantPolicy,
    NegotiationContext,
    NegotiationEngine,
    Stance,
    new_negotiation_id,
)
from app.audit import AuditLogger
from app.matching.catalog import load_products

# Keep library chatter quiet; we print the audit trail ourselves.
logging.basicConfig(level=logging.WARNING)

PRODUCTS = load_products()

# Same policies as production (app/checkout/service.py) — nothing scenario-
# specific. The economics alone decide whether these pairings work.
POLICY_A = dict(min_viable_discount_pct=1.0, stance=Stance.AGGRESSIVE)
POLICY_B = dict(min_viable_discount_pct=2.0, stance=Stance.CONSERVATIVE)


def _context(nid: str, a, b, affinity: float) -> NegotiationContext:
    return NegotiationContext(
        negotiation_id=nid,
        product_a_id=a.product_id, product_b_id=b.product_id,
        merchant_a_id=a.merchant_id, merchant_b_id=b.merchant_id,
        price_a_inr=a.price_inr, price_b_inr=b.price_inr,
        cost_a_inr=a.cost_price_inr, cost_b_inr=b.cost_price_inr,
        role_a=a.product_role, role_b=b.product_role,
        affinity_score=affinity,
    )


def _print_trail(audit: AuditLogger, cid: str) -> None:
    print("-" * 78)
    for e in audit.get_story(cid):
        print(f"  #{e.seq:<2} [{e.actor:<18}] {e.event_type.value}")
        print(f"       {e.reasoning}")
    print("-" * 78)


def run(title: str, a, b, affinity: float) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)
    print(f"  A: {a.name} — Rs.{a.price_inr} (cost Rs.{a.cost_price_inr}, "
          f"margin {a.margin_pct:.1f}%, {a.product_role})")
    print(f"  B: {b.name} — Rs.{b.price_inr} (cost Rs.{b.cost_price_inr}, "
          f"margin {b.margin_pct:.1f}%, {b.product_role})")

    audit = AuditLogger(":memory:")
    agent_a = MerchantAgent(MerchantPolicy(merchant_id=a.merchant_id, **POLICY_A))
    agent_b = MerchantAgent(MerchantPolicy(merchant_id=b.merchant_id, **POLICY_B))
    engine = NegotiationEngine(agent_a, agent_b, audit, max_rounds=5)
    nid = new_negotiation_id()
    result = engine.negotiate(_context(nid, a, b, affinity), a, b)

    _print_trail(audit, nid)

    print(f"  RESULT: {result.status.value.upper()} — {result.reason}")
    if result.bundle:
        bd = result.bundle
        print(f"  Merchant A discount: {bd.merchant_a_discount_pct:.2f}% "
              f"(Rs.{a.price_inr - bd.merchant_a_amount_inr})")
        print(f"  Merchant B discount: {bd.merchant_b_discount_pct:.2f}% "
              f"(Rs.{b.price_inr - bd.merchant_b_amount_inr})")
        print(f"  Blended bundle discount: {bd.discount_pct:.2f}% off — "
              f"customer pays Rs.{bd.bundle_price_inr} "
              f"(was Rs.{bd.original_total_inr})")
        print(f"  Route split -> A: Rs.{bd.merchant_a_amount_inr}  |  "
              f"B: Rs.{bd.merchant_b_amount_inr}")
        print(f"  Customer copy: {result.offer_copy}")
    else:
        print("  No bundle offer produced — nothing shown to the customer.")


def main() -> None:
    run(
        "SCENARIO 1 — LumenBook Pro 15 + Slim 13 Sleeve (expect CONVERGENCE)",
        PRODUCTS["a_lap_15biz"], PRODUCTS["b_slv_13sleeve"], affinity=0.524,
    )

    run(
        "SCENARIO 2 — Predator 16 Gaming Laptop + Cable Management Roll "
        "(expect WALK-AWAY)",
        PRODUCTS["a_lap_16gaming"], PRODUCTS["b_org_cableroll"], affinity=0.40,
    )


if __name__ == "__main__":
    main()
