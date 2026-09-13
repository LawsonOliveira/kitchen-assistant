"""Pricing core — expected values are hand-computed in PLAN.md, never taken from running the code."""

from decimal import Decimal

import pytest

from costs_mcp.pricing import (
    cmv_per_portion,
    format_brl,
    format_brl_min,
    format_unit_cost,
    min_price,
    min_price_with_packaging,
    price_alerts,
    price_scenarios,
    recipe_cmv,
    round_up_commercial,
    unit_cost,
)

FEE = Decimal("0.10")
FOUR_PLACES = Decimal("0.0001")


def test_unit_cost_is_total_paid_over_quantity_purchased():
    # Arroz branco tipo 1: R$ 24.90 for 5 kg = 5000 g -> 0.00498 R$/g
    assert unit_cost(Decimal("24.90"), Decimal("5000")) == Decimal("0.00498")


def test_min_price_is_cmv_over_ninety_percent():
    # Reference dish CMV per portion 2.7159625 with a 10% platform fee
    assert min_price(Decimal("2.7159625"), Decimal("0.10")) == Decimal("2.7159625") / Decimal("0.9")


# --- Reference dish (PLAN.md Loop 1): yield 4 portions -------------------------------------------

REFERENCE_LINES = [
    (Decimal("400"), unit_cost(Decimal("24.90"), Decimal("5000"))),  # Arroz branco tipo 1
    (Decimal("600"), unit_cost(Decimal("28.00"), Decimal("2000"))),  # Peito de frango
    (Decimal("10"), unit_cost(Decimal("6.00"), Decimal("300"))),  # Alho
    (Decimal("30"), unit_cost(Decimal("9.00"), Decimal("1000"))),  # Óleo de soja (ml)
    (Decimal("1"), unit_cost(Decimal("1.85"), Decimal("1000"))),  # Sal, pinch = 1 g
]


def test_reference_dish_cmv():
    assert recipe_cmv(REFERENCE_LINES) == Decimal("10.86385")
    assert cmv_per_portion(Decimal("10.86385"), 4) == Decimal("2.7159625")


@pytest.mark.parametrize("portions", [0, -1])
def test_cmv_per_portion_rejects_non_positive_yield(portions):
    with pytest.raises(ValueError):
        cmv_per_portion(Decimal("10"), portions)


def test_reference_dish_scenarios():
    scenarios = price_scenarios(Decimal("2.7159625"), None, FEE)
    assert [s.target_cmv_pct for s in scenarios] == [Decimal("0.35"), Decimal("0.30"), Decimal("0.25")]
    assert [s.display_price for s in scenarios] == [Decimal("7.90"), Decimal("9.90"), Decimal("10.90")]
    assert scenarios[0].owner_receives == Decimal("7.11")
    assert [s.profit for s in scenarios] == [Decimal("4.3940375"), Decimal("6.1940375"), Decimal("7.0940375")]
    assert [s.margin_on_sale.quantize(FOUR_PLACES) for s in scenarios] == [Decimal("0.5562"), Decimal("0.6257"), Decimal("0.6508")]
    assert all(s.profit_after_packaging is None and not s.below_min for s in scenarios)
    assert scenarios[0].raw_price.quantize(FOUR_PLACES) == Decimal("7.7599")


def test_scenarios_with_packaging():
    # Packaging: pack of 50 for R$ 25.00 -> 0.50 per order
    scenarios = price_scenarios(Decimal("2.7159625"), Decimal("0.50"), FEE)
    assert scenarios[1].profit_after_packaging == Decimal("5.6940375")


@pytest.mark.parametrize(
    "price, expected",
    [("7.90", "7.90"), ("7.91", "8.90"), ("27.43", "27.90"), ("27.95", "28.90"), ("7.7598928", "7.90")],
)
def test_round_up_commercial_ends_in_90_and_never_goes_down(price, expected):
    assert round_up_commercial(Decimal(price)) == Decimal(expected)


def test_display_strings():
    assert format_unit_cost(Decimal("24.90"), Decimal("5000"), "g") == "R$ 4,98/kg"
    assert format_unit_cost(Decimal("28.00"), Decimal("2000"), "g") == "R$ 14,00/kg"
    assert format_unit_cost(Decimal("9.00"), Decimal("1000"), "ml") == "R$ 9,00/L"
    assert format_unit_cost(Decimal("24.00"), Decimal("30"), "unit") == "R$ 0,80/un"
    assert format_brl(Decimal("10.86385")) == "R$ 10,86"
    assert format_brl(Decimal("1234.5")) == "R$ 1.234,50"
    assert format_brl_min(min_price(Decimal("2.7159625"), FEE)) == "R$ 3,02"


def test_minimum_prices_round_up_so_they_never_lose_money():
    with_packaging = min_price_with_packaging(Decimal("2.7159625"), Decimal("0.50"), FEE)
    assert with_packaging.quantize(FOUR_PLACES) == Decimal("3.5733")
    assert format_brl_min(with_packaging) == "R$ 3,58"  # half-up would show a losing R$ 3,57
    assert format_brl_min(Decimal("3.3510694")) == "R$ 3,36"
    assert format_brl_min(Decimal("8.1844028")) == "R$ 8,19"


# --- Alerts after a cost change (selected scenario 35% at R$ 7,90) ------------------------------


def test_cost_increase_above_target_is_a_warning_only():
    alerts = price_alerts(Decimal("3.0159625"), Decimal("7.90"), Decimal("0.35"), FEE)
    assert [(a.code, a.severity) for a in alerts] == [("cmv_pct_above_target", "warning")]
    assert alerts[0].actual_cmv_pct.quantize(FOUR_PLACES) == Decimal("0.3818")
    assert alerts[0].target_cmv_pct == Decimal("0.35")


def test_cost_above_what_the_owner_receives_is_critical():
    alerts = price_alerts(Decimal("7.3659625"), Decimal("7.90"), Decimal("0.35"), FEE)
    assert [(a.code, a.severity) for a in alerts] == [("below_min", "critical"), ("cmv_pct_above_target", "warning")]
    assert alerts[0].min_price_display == "R$ 8,19"


def test_packaging_adds_its_own_critical_alert():
    alerts = price_alerts(Decimal("7.3659625"), Decimal("7.90"), Decimal("0.35"), FEE, Decimal("0.50"))
    assert [a.code for a in alerts] == ["below_min", "below_min_with_packaging", "cmv_pct_above_target"]
    assert alerts[1].min_price_display == "R$ 8,74"


@pytest.mark.parametrize("cmv", [Decimal("2.7159625"), Decimal("2.50")])
def test_no_alert_within_target_or_after_a_cost_decrease(cmv):
    assert price_alerts(cmv, Decimal("7.90"), Decimal("0.35"), FEE) == []
