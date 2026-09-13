import pytest
from conftest import EVIDENCE, ingredient, make_recipe, viable_profile

from costs_mcp import operations
from costs_mcp.operations import DomainError


def creme_dish(conn, extra=()):
    viable_profile(conn)
    recipe = make_recipe([ingredient("Arroz branco tipo 1", 100, "g"), ingredient("Creme de leite", 300, "g", None), *extra])
    return operations.register_candidate_dish(conn, recipe, 4, 4, EVIDENCE)["dish_id"]


def quote_creme(conn, price="5.00", source="web_estimate"):
    operations.record_price_quote(
        conn, ingredient_name="Creme de leite", kind="food", package_quantity="200", package_unit="g",
        package_price=price, source=source, source_url="https://mercado.example/creme-de-leite", evidence=EVIDENCE,
    )


def test_missing_item_is_priced_in_whole_packages(conn):
    dish = creme_dish(conn)
    quote_creme(conn)
    fit = operations.check_budget_fit(conn, dish)
    [item] = fit["missing_items"]
    assert item["ingredient"] == "Creme de leite"
    assert item["packages_needed"] == 2
    assert item["package_price_display"] == "R$ 5,00"
    assert item["subtotal_display"] == "R$ 10,00"
    assert item["price_source"] == "web_estimate"
    assert (fit["total_display"], fit["budget_remaining_display"], fit["fits"], fit["shortfall_display"]) == (
        "R$ 10,00", "R$ 80,00", True, None)


def test_budget_fit_reports_the_shortfall(conn):
    dish = creme_dish(conn)
    quote_creme(conn, price="50.00")
    fit = operations.check_budget_fit(conn, dish)
    assert (fit["total_display"], fit["fits"], fit["shortfall_display"]) == ("R$ 100,00", False, "R$ 20,00")


def test_a_quote_does_not_touch_the_budget(conn):
    creme_dish(conn)
    quote_creme(conn)
    assert operations.get_state_summary(conn)["budget_remaining_display"] == "R$ 80,00"


def test_web_estimate_cannot_enter_cmv_until_confirmed(conn):
    dish = creme_dish(conn)
    quote_creme(conn)
    with pytest.raises(DomainError) as error:
        operations.compute_dish_cost(conn, dish_id=dish)
    assert error.value.code == "unconfirmed_price"
    assert error.value.details["ingredients"] == ["Creme de leite"]

    quote_creme(conn, source="owner_confirmed")
    cost = operations.compute_dish_cost(conn, dish_id=dish)
    creme = next(line for line in cost["lines"] if line["ingredient"] == "Creme de leite")
    assert creme["cost_display"] == "R$ 7,50"
    assert creme["price_source"] == "owner_confirmed"


def test_missing_item_without_any_quote_fails_loud(conn):
    dish = creme_dish(conn, extra=[ingredient("Queijo coalho", 200, "g", None)])
    quote_creme(conn)
    with pytest.raises(DomainError) as error:
        operations.check_budget_fit(conn, dish)
    assert error.value.code == "missing_price_quote"
    assert error.value.details["ingredients"] == ["Queijo coalho"]
