"""Minimal in-memory inventory with reserve/release.

Seeded from the mock catalog's ``stock_qty``. Reserving decrements available
stock; releasing (a saga compensation) restores it. In-memory is fine for the
demo — the point is the reserve/release contract the saga depends on.
"""
import threading
from uuid import uuid4

from app.matching.catalog import load_products


class OutOfStock(Exception):
    """Raised when a product cannot be reserved."""


class InventoryService:
    def __init__(self, stock: dict[str, int] | None = None):
        if stock is None:
            stock = {p.product_id: p.stock_qty for p in load_products().values()}
        self._stock = dict(stock)
        self._reservations: dict[str, str] = {}  # reservation_id -> product_id
        self._lock = threading.Lock()

    def reserve(self, product_id: str) -> str:
        with self._lock:
            available = self._stock.get(product_id, 0)
            if available <= 0:
                raise OutOfStock(f"'{product_id}' is out of stock")
            self._stock[product_id] = available - 1
            rid = f"resv_{uuid4().hex[:10]}"
            self._reservations[rid] = product_id
            return rid

    def release(self, reservation_id: str) -> None:
        with self._lock:
            product_id = self._reservations.pop(reservation_id, None)
            if product_id is not None:
                self._stock[product_id] = self._stock.get(product_id, 0) + 1

    def set_stock(self, product_id: str, qty: int) -> None:
        with self._lock:
            self._stock[product_id] = qty

    def stock_of(self, product_id: str) -> int:
        return self._stock.get(product_id, 0)
