"""Catalog route — powers the storefront grid."""
import logging

from fastapi import APIRouter

from app.matching import find_companions
from app.matching.catalog import load_merchants

router = APIRouter(tags=["catalog"])
logger = logging.getLogger("api.catalog")


def _has_companion(product_id: str) -> bool:
    """Same matching engine + threshold the checkout flow uses.

    Computed here (not guessed by the frontend) so the storefront's "Buy Now"
    availability can never drift from what actually happens on checkout —
    embeddings are cached, so this is cheap even across the whole catalog.
    """
    try:
        return len(find_companions(product_id, top_k=1)) > 0
    except Exception as exc:  # never let a matching hiccup break the storefront
        logger.warning("Companion check failed for '%s': %s", product_id, exc)
        return True  # fail open — let checkout be the source of truth


@router.get("/catalog")
def catalog() -> dict:
    """Return every merchant and its products for the storefront."""
    merchants = []
    for m in load_merchants():
        merchants.append({
            "merchant_id": m.merchant_id,
            "name": m.name,
            "category": m.category,
            "description": m.description,
            "products": [
                {
                    "product_id": p.product_id,
                    "name": p.name,
                    "description": p.description,
                    "category": p.category,
                    "price_inr": p.price_inr,
                    "mrp_inr": p.effective_mrp,
                    "discount_pct": p.discount_pct,
                    "stock_qty": p.stock_qty,
                    "tags": p.tags,
                    "has_companion": _has_companion(p.product_id),
                }
                for p in m.products
            ],
        })
    return {"merchants": merchants}
