"""Pricing core — expected values are hand-computed in PLAN.md, never taken from running the code."""

from decimal import Decimal

from costs_mcp.pricing import min_price, unit_cost


def test_unit_cost_is_total_paid_over_quantity_purchased():
    # Arroz branco tipo 1: R$ 24.90 for 5 kg = 5000 g -> 0.00498 R$/g
    assert unit_cost(Decimal("24.90"), Decimal("5000")) == Decimal("0.00498")


def test_min_price_is_cmv_over_ninety_percent():
    # Reference dish CMV per portion 2.7159625 with a 10% platform fee
    assert min_price(Decimal("2.7159625"), Decimal("0.10")) == Decimal("2.7159625") / Decimal("0.9")
