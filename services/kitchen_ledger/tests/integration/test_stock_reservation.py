from decimal import Decimal

import pytest
from conftest import EVIDENCE, ingredient, make_recipe, pantry_stock, viable_profile

from kitchen_ledger import operations
from kitchen_ledger.operations import DomainError


def tomato_dish(conn, grams, name, yield_portions=4, launch_batch_portions=4):
    recipe = make_recipe([ingredient("Tomate", grams, "g")], name=name, yield_portions=yield_portions)
    return operations.register_candidate_dish(conn, recipe, yield_portions, launch_batch_portions, EVIDENCE)["dish_id"]


def test_accepted_dish_reserves_its_launch_batch(conn):
    viable_profile(conn)
    dish_a = tomato_dish(conn, 1500, "Molho A")
    operations.accept_dish(conn, dish_a)
    dish_b = tomato_dish(conn, 800, "Molho B")

    with pytest.raises(DomainError) as error:
        operations.accept_dish(conn, dish_b)
    assert error.value.code == "insufficient_stock"
    [shortfall] = error.value.details["shortfalls"]
    assert (shortfall["ingredient"], Decimal(shortfall["short_base"]), shortfall["base_unit"]) == ("Tomate", Decimal("300"), "g")


def test_launch_batch_scales_the_recipe(conn):
    viable_profile(conn)
    dish = tomato_dish(conn, 1500, "Molho grande", yield_portions=4, launch_batch_portions=8)
    match = operations.check_pantry_match(conn, dish)
    [missing] = match["missing"]
    assert (missing["ingredient"], Decimal(missing["short_base"])) == ("Tomate", Decimal("1000"))


def test_purchase_adds_availability_without_touching_pantry_stock(conn):
    viable_profile(conn)
    dish_a = tomato_dish(conn, 1500, "Molho A")
    operations.accept_dish(conn, dish_a)
    dish_b = tomato_dish(conn, 800, "Molho B")

    operations.register_purchase(
        conn, ingredient_name="Tomate", kind="food", packages=1, package_quantity="1", package_unit="kg",
        package_price="8.00", price_source="owner_confirmed", source_url=None, dish_id=dish_b, evidence=EVIDENCE,
    )
    assert pantry_stock(conn, "Tomate") == Decimal("2000")
    operations.accept_dish(conn, dish_b)  # 2000 + 1000 - 1500 = 1500 available >= 800


def test_an_accepted_dish_counts_its_own_reservation_as_available(conn):
    # Loop 3 scenario 05: budget_fit on the accepted sauce reported its own reserved 2 kg of tomato as missing.
    viable_profile(conn)
    dish = tomato_dish(conn, 1000, "Molho da vó", yield_portions=4, launch_batch_portions=8)
    operations.accept_dish(conn, dish)
    assert operations.check_pantry_match(conn, dish)["missing"] == []
    assert operations.check_budget_fit(conn, dish)["missing_items"] == []


def test_stock_she_already_has_is_a_correction_not_a_purchase(conn):
    # Full run 20260915-095503, scenario 03 trials 1 and 2: Dona Maria cancelled the purchase and said the creme de
    # leite was already at home. The only tool that adds stock was register_purchase, so Dona Sálvia "bought" it —
    # R$ 3,49 off a budget she never spent, and "nothing was bought" failed. Her pantry being out of date is a
    # correction, like a price she corrects, and it must not touch the budget.
    before = conn.execute("SELECT remaining FROM budget_status").fetchone()[0]
    result = operations.correct_pantry_stock(conn, ingredient_name="Creme de leite", quantity="200", unit="ml",
                                             evidence="já tenho uma caixinha em casa")
    assert result["stock_display"] == "200 ml"
    assert conn.execute("SELECT count(*) FROM purchases").fetchone()[0] == 0
    assert conn.execute("SELECT remaining FROM budget_status").fetchone()[0] == before


def test_a_stock_correction_replaces_what_the_spreadsheet_said(conn):
    operations.correct_pantry_stock(conn, ingredient_name="Arroz branco tipo 1", quantity="1", unit="kg",
                                    evidence="só sobrou um quilo")
    operations.correct_pantry_stock(conn, ingredient_name="Arroz branco tipo 1", quantity="2", unit="kg",
                                    evidence="achei mais um pacote")
    stock = conn.execute("SELECT s.quantity_base FROM pantry_stock s JOIN ingredients i ON i.id = s.ingredient_id"
                         " WHERE i.name = 'Arroz branco tipo 1'").fetchone()[0]
    assert stock == 2000
