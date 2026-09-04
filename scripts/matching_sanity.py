"""Sanity check for the semantic matching engine.

Prints top companion matches from the *other* merchant for three different
laptops, so the cross-merchant affinities can be eyeballed.

Run:
    python -m scripts.matching_sanity
"""
import logging

from app.matching import find_companion_products, get_matcher

# Show the engine's reasoning (threshold decisions, cache hits) as it runs.
logging.basicConfig(level=logging.INFO, format="  [%(name)s] %(message)s")

LAPTOPS = [
    ("a_lap_15biz", "15-inch business laptop"),
    ("a_lap_13ultra", "13-inch ultrabook"),
    ("a_lap_16gaming", "16-inch gaming laptop"),
]


def main() -> None:
    matcher = get_matcher()
    print(f"\nMatching engine: model={matcher.model_name}, "
          f"min_affinity={matcher.min_affinity}\n")

    for product_id, label in LAPTOPS:
        source = matcher._products.get(product_id) if matcher._ready else None
        print("=" * 68)
        print(f"SOURCE: {label}  ({product_id})")
        matches = find_companion_products(product_id, top_k=3)
        source = matcher._products[product_id]
        print(f"        {source.name} — Rs.{source.price_inr}")
        print("-" * 68)
        if not matches:
            print("  (no companion cleared the affinity threshold)")
        for rank, m in enumerate(matches, 1):
            print(
                f"  {rank}. {m.affinity_score:.3f}  {m.product.name}\n"
                f"        {m.product.category} · Rs.{m.product.price_inr} · "
                f"{m.product.product_id}"
            )
        print()


if __name__ == "__main__":
    main()
