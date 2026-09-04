"""Tests for the deterministic per-SKU margin economics."""
import pytest

from app.agents.economics import compute_sku_floor


def test_anchor_ceiling_matches_worked_example():
    # LumenBook Pro 15: price 84999, cost 76499 -> ~10.0% margin.
    # 82% retention -> ~1.8% ceiling, floor lands at exactly 8.2%.
    sku = compute_sku_floor(84999, 76499, "anchor")
    assert round(sku.margin_pct, 1) == 10.0
    assert round(sku.discount_ceiling_pct, 1) == 1.8
    assert round(sku.margin_floor_pct, 1) == 8.2


def test_companion_ceiling_is_generous():
    # Sleeve: price 1299, cost 585 -> ~55% margin, 35% retention.
    sku = compute_sku_floor(1299, 585, "companion")
    assert 50 <= sku.margin_pct <= 60
    assert 20.0 <= sku.discount_ceiling_pct <= 40.0
    assert sku.margin_floor_pct > 0


def test_ceiling_never_exceeds_role_band():
    # Absurdly fat margin should still clamp to the role's max ceiling.
    sku = compute_sku_floor(1000, 50, "companion")  # 95% margin
    assert sku.discount_ceiling_pct <= 40.0
    # Absurdly fat margin on an anchor role clamps to the anchor's max.
    sku = compute_sku_floor(1000, 50, "anchor")
    assert sku.discount_ceiling_pct <= 3.0


def test_ceiling_never_sells_below_cost():
    # Paper-thin margin: even the role's minimum ceiling can't push the
    # merchant below breakeven.
    sku = compute_sku_floor(1000, 992, "anchor")  # 0.8% margin
    assert sku.discount_ceiling_pct <= sku.margin_pct
    assert sku.margin_floor_pct >= 0


def test_cost_above_price_rejected():
    with pytest.raises(ValueError):
        compute_sku_floor(1000, 1500, "anchor")
