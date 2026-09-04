"""Catalog loading — reads mock merchant catalogs from data/*.json."""
import json
from pathlib import Path

from app.models import Merchant, Product

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

CATALOG_FILES = ["merchant_a.json", "merchant_b.json"]


def load_merchants(data_dir: Path = DATA_DIR) -> list[Merchant]:
    """Load every merchant catalog from the data directory."""
    merchants: list[Merchant] = []
    for filename in CATALOG_FILES:
        path = data_dir / filename
        with open(path, "r", encoding="utf-8") as fh:
            merchants.append(Merchant.model_validate(json.load(fh)))
    return merchants


def load_products(data_dir: Path = DATA_DIR) -> dict[str, Product]:
    """Return all products across all merchants, keyed by product_id."""
    products: dict[str, Product] = {}
    for merchant in load_merchants(data_dir):
        for product in merchant.products:
            products[product.product_id] = product
    return products
