import pytest
from conftest import EVIDENCE, ingredient, make_recipe, viable_profile

from costs_mcp import operations
from costs_mcp.operations import DomainError


def creme_dish(conn, extra=()):
    viable_profile(conn)
    recipe = make_recipe([ingredient("Arroz branco tipo 1", 100, "g"), ingredient("Creme de leite", 300, "g", None), *extra])
    return operations.register_candidate_dish(conn, recipe, 4, 4, EVIDENCE)["dish_id"]


def quote_creme(conn, price="5.00", source="web_estimate"):
    return operations.record_price_quote(
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


def test_budget_fit_states_what_remains_after_buying(conn):
    # Smoke trial 01 (2026-09-13): with only budget_remaining_display (R$ 80,00, before buying) Dona Sálvia told the owner
    # "depois da compra ainda sobram R$ 80,00" for a R$ 13,89 purchase.
    dish = creme_dish(conn)
    quote_creme(conn)
    assert operations.check_budget_fit(conn, dish)["budget_remaining_after_purchase_display"] == "R$ 70,00"


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


def test_launch_menu_lists_accepted_dishes_and_the_shopping_list(conn):
    from conftest import reference_recipe

    viable_profile(conn)
    dish = operations.register_candidate_dish(conn, reference_recipe(), 4, 4, EVIDENCE)["dish_id"]
    operations.accept_dish(conn, dish)
    operations.select_price_scenario(conn, dish, "0.35")
    operations.register_purchase(
        conn, ingredient_name="Creme de leite", kind="food", packages=2, package_quantity="200", package_unit="g",
        package_price="5.00", price_source="owner_confirmed", source_url=None, dish_id=dish, evidence=EVIDENCE,
    )
    menu = operations.get_launch_menu(conn)
    [item] = menu["dishes"]
    assert (item["name"], item["display_price"], item["cmv_per_portion_display"]) == ("Arroz com frango", "R$ 7,90", "R$ 2,72")
    [purchase] = menu["shopping_list"]
    assert (purchase["ingredient"], purchase["packages"], purchase["subtotal_display"]) == ("Creme de leite", 2, "R$ 10,00")
    assert purchase["dish_names"] == ["Arroz com frango"]
    assert (menu["purchases_total_display"], menu["budget_remaining_display"]) == ("R$ 10,00", "R$ 70,00")


def test_missing_item_without_any_quote_fails_loud(conn):
    dish = creme_dish(conn, extra=[ingredient("Queijo coalho", 200, "g", None)])
    quote_creme(conn)
    with pytest.raises(DomainError) as error:
        operations.check_budget_fit(conn, dish)
    assert error.value.code == "missing_price_quote"
    assert error.value.details["ingredients"] == ["Queijo coalho"]


def test_a_quote_returns_its_package_so_the_owner_can_confirm_exactly_that_quote(conn):
    # Loop 3 scenario 02: without the package, orchestrator could not send confirm_price_quote and asked the owner again.
    quote = quote_creme(conn)
    assert {key: quote[key] for key in ("package_quantity", "package_unit", "package_price", "package_price_display")} == {
        "package_quantity": "200", "package_unit": "g", "package_price": "5.00", "package_price_display": "R$ 5,00"}


def test_oil_to_taste_is_a_small_estimate_in_ml_not_a_conversion_question(conn):
    # Loop 3 scenario 02: "óleo a gosto" asked the owner how many grams 1 ml of oil weighs.
    recipe = make_recipe([ingredient("Peito de frango", 600, "g"), ingredient("Óleo de soja", None, "to_taste")])
    cost = operations.compute_dish_cost(conn, recipe=recipe)
    oil = next(line for line in cost["lines"] if line["ingredient"] == "Óleo de soja")
    assert "error" not in cost and oil["quantity_used_display"] == "1 ml" and oil["is_estimate"] is True


def test_a_web_estimate_never_replaces_a_price_the_owner_already_has(conn):
    # Loop 3 scenario 02: an estimate of R$ 15,99/kg superseded the spreadsheet's R$ 28,00 / 2 kg for Peito de frango.
    with pytest.raises(DomainError) as error:
        operations.record_price_quote(conn, ingredient_name="Peito de frango", kind="food", package_quantity="1", package_unit="kg",
                                      package_price="15.99", source="web_estimate", source_url="https://mercado.example/frango",
                                      evidence=EVIDENCE)
    assert error.value.code == "price_already_known" and error.value.details["unit_cost_display"] == "R$ 14,00/kg"
    assert operations.compute_dish_cost(conn, recipe=make_recipe([ingredient("Peito de frango", 1000, "g")]))["recipe_cmv_display"] == "R$ 14,00"


def test_a_newer_web_estimate_may_replace_an_older_estimate(conn):
    quote_creme(conn, price="5.00")
    assert quote_creme(conn, price="4.50")["package_price_display"] == "R$ 4,50"


def test_a_gap_error_lists_every_gap_at_once(conn):
    # Full run 20260913-192309: Dona Sálvia asked 21 separate questions in one conversation because each budget_fit
    # answered with one gap at a time; with every gap in the first answer she can ask them all in one clarify.
    viable_profile(conn)
    recipe = make_recipe([ingredient("Creme de leite", 300, "g", None),
                          ingredient("Cobertura de chocolate", 1, "unit", "Cobertura de chocolate")])
    dish = operations.register_candidate_dish(conn, recipe, 4, 4, EVIDENCE)["dish_id"]
    with pytest.raises(DomainError) as error:
        operations.check_budget_fit(conn, dish)
    assert error.value.details["ingredients"] == ["Creme de leite"]
    assert [item["ingredient"] for item in error.value.details["conversions"]] == ["Cobertura de chocolate"]
