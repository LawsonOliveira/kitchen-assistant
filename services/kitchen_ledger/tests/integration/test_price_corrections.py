from decimal import Decimal

import pytest
from conftest import EVIDENCE, ingredient, make_recipe, reference_recipe, viable_profile

from kitchen_ledger import operations
from kitchen_ledger.operations import DomainError


def reference_dish(conn):
    viable_profile(conn)
    return operations.register_candidate_dish(conn, reference_recipe(), 4, 4, EVIDENCE)["dish_id"]


def accepted_reference_dish(conn):
    dish = reference_dish(conn)
    operations.accept_dish(conn, dish)
    operations.select_price_scenario(conn, dish, "0.35")
    return dish


def line(cost, name):
    return next(item for item in cost["lines"] if item["ingredient"] == name)


def test_reference_dish_cost_is_explained_with_display_strings(conn):
    cost = operations.compute_dish_cost(conn, dish_id=reference_dish(conn))
    assert cost["recipe_cmv_display"] == "R$ 10,86"
    assert cost["cmv_per_portion_display"] == "R$ 2,72"
    assert cost["min_price_display"] == "R$ 3,02"
    assert [s["display_price"] for s in cost["scenarios"]] == ["R$ 7,90", "R$ 9,90", "R$ 10,90"]
    rice = line(cost, "Arroz branco tipo 1")
    assert (rice["total_price_paid_display"], rice["quantity_purchased_display"], rice["unit_cost_display"],
            rice["cost_display"]) == ("R$ 24,90", "5 kg", "R$ 4,98/kg", "R$ 1,99")
    assert line(cost, "Sal")["is_estimate"] is True
    assert line(cost, "Arroz branco tipo 1")["is_estimate"] is False


def test_selected_price_is_the_rounded_display_price(conn):
    dish = accepted_reference_dish(conn)
    assert conn.execute("SELECT selected_price FROM dishes WHERE id = %s", (dish,)).fetchone()[0] == Decimal("7.90")


def test_price_increase_above_the_chosen_target_warns(conn):
    dish = accepted_reference_dish(conn)
    result = operations.correct_price(conn, "Peito de frango", "32.00", "2", "kg", "paguei R$ 32 no frango")
    assert [(alert["dish_id"], alert["code"]) for alert in result["alerts"]] == [(dish, "cmv_pct_above_target")]


def test_price_increase_below_minimum_is_critical(conn):
    accepted_reference_dish(conn)
    result = operations.correct_price(conn, "Peito de frango", "90.00", "2", "kg", EVIDENCE)
    assert [(alert["code"], alert["severity"]) for alert in result["alerts"]] == [
        ("below_min", "critical"), ("cmv_pct_above_target", "warning")]


def test_price_decrease_raises_no_alert(conn):
    accepted_reference_dish(conn)
    assert operations.correct_price(conn, "Peito de frango", "20.00", "2", "kg", EVIDENCE)["alerts"] == []


def test_latest_purchase_price_is_used_not_an_average(conn):
    dish = accepted_reference_dish(conn)
    operations.register_purchase(
        conn, ingredient_name="Peito de frango", kind="food", packages=1, package_quantity="1", package_unit="kg",
        package_price="16.00", price_source="owner_confirmed", source_url=None, dish_id=dish, evidence=EVIDENCE,
    )
    chicken = line(operations.compute_dish_cost(conn, dish_id=dish), "Peito de frango")
    assert (chicken["unit_cost_display"], chicken["cost_display"]) == ("R$ 16,00/kg", "R$ 9,60")


def test_owner_conversion_factor_allows_cross_dimension_use(conn):
    viable_profile(conn)
    recipe = make_recipe([ingredient("Cobertura de chocolate", 200, "g")])
    dish = operations.register_candidate_dish(conn, recipe, 4, 4, EVIDENCE)["dish_id"]
    with pytest.raises(DomainError) as error:
        operations.compute_dish_cost(conn, dish_id=dish)
    assert error.value.code == "missing_conversion"

    operations.set_conversion_factor(conn, "Cobertura de chocolate", "unit", "1000", "g", "a embalagem tem 1 kg")
    assert line(operations.compute_dish_cost(conn, dish_id=dish), "Cobertura de chocolate")["cost_display"] == "R$ 15,98"
