"""End-to-end session demo with a single correlation_id.

Runs matching -> negotiation under ONE correlation_id, persisting every step to
the shared audit database (data/audit.db). Then prints the same ordered story
the GET /audit/{correlation_id} endpoint would return, and the id to query.

Run:
    python -m scripts.session_demo
    # then, with the API running (uvicorn app.main:app):
    #   GET http://localhost:8000/audit/<printed correlation_id>
"""
import logging
from uuid import uuid4

from app.agents import (
    MerchantAgent,
    MerchantPolicy,
    NegotiationContext,
    NegotiationEngine,
    Stance,
    new_negotiation_id,
)
from app.audit import get_audit_logger
from app.matching import find_companions
from app.matching.catalog import load_products

logging.basicConfig(level=logging.WARNING)

PRODUCTS = load_products()
SOURCE = PRODUCTS["a_lap_15biz"]  # 15-inch business laptop


def main() -> None:
    audit = get_audit_logger()
    correlation_id = f"sess_{uuid4().hex[:10]}"

    print(f"\nSession correlation_id: {correlation_id}\n")

    # 1. Matching (logs AFFINITY_SCORED + MATCHING_PERFORMED under this session)
    matches = find_companions(
        SOURCE.product_id, top_k=1,
        audit=audit, correlation_id=correlation_id,
    )
    if not matches:
        print("No companion found — nothing to negotiate.")
        return
    companion = matches[0].product
    affinity = matches[0].affinity_score

    # 2. Negotiation under the same correlation_id.
    agent_a = MerchantAgent(MerchantPolicy(
        merchant_id=SOURCE.merchant_id, min_margin_pct=88,
        max_discount_pct=15, min_viable_discount_pct=5,
        stance=Stance.AGGRESSIVE))
    agent_b = MerchantAgent(MerchantPolicy(
        merchant_id=companion.merchant_id, min_margin_pct=80,
        max_discount_pct=12, min_viable_discount_pct=4,
        stance=Stance.CONSERVATIVE))

    ctx = NegotiationContext(
        negotiation_id=new_negotiation_id(),
        product_a_id=SOURCE.product_id,
        product_b_id=companion.product_id,
        merchant_a_id=SOURCE.merchant_id,
        merchant_b_id=companion.merchant_id,
        price_a_inr=SOURCE.price_inr,
        price_b_inr=companion.price_inr,
        affinity_score=affinity,
        correlation_id=correlation_id,
    )
    NegotiationEngine(agent_a, agent_b, audit, max_rounds=5).negotiate(
        ctx, SOURCE, companion
    )

    # 3. Print the story exactly as the endpoint would render it.
    print("=" * 74)
    print("THE STORY (GET /audit/%s)" % correlation_id)
    print("=" * 74)
    for e in audit.get_story(correlation_id):
        ts = e.timestamp.strftime("%H:%M:%S")
        print(f"[{ts}] {e.event_type.value.upper()} · {e.actor}")
        print(f"        {e.reasoning}")
    print("=" * 74)
    print(f"\nQuery it live:  GET /audit/{correlation_id}\n")


if __name__ == "__main__":
    main()
