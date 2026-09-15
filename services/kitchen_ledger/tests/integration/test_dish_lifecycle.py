from decimal import Decimal

import pytest
from conftest import EVIDENCE, ingredient, make_recipe, pantry_stock, viable_profile

from kitchen_ledger import operations
from kitchen_ledger.operations import DomainError

RICE = [ingredient("Arroz branco tipo 1", 400, "g")]


def buy_rice(conn, dish_id):
    return operations.register_purchase(
        conn, ingredient_name="Arroz branco tipo 1", kind="food", packages=1, package_quantity="1",
        package_unit="kg", package_price="5.00", price_source="owner_confirmed", source_url=None,
        dish_id=dish_id, evidence=EVIDENCE,
    )


def dish_status(conn, dish_id):
    return conn.execute("SELECT status, rejected_reason FROM dishes WHERE id = %s", (dish_id,)).fetchone()


def test_food_purchase_requires_a_dish(conn):
    with pytest.raises(DomainError) as error:
        buy_rice(conn, None)
    assert error.value.code == "dish_required"


def test_packaging_purchase_needs_no_dish(conn):
    operations.register_purchase(
        conn, ingredient_name="Marmita 500 ml", kind="packaging", packages=1, package_quantity="50",
        package_unit="un", package_price="25.00", price_source="owner_confirmed", source_url=None,
        dish_id=None, evidence=EVIDENCE,
    )


def test_no_purchase_for_a_dish_she_cannot_cook(conn):
    viable_profile(conn)
    dish = operations.register_candidate_dish(conn, make_recipe(RICE, ["oven"]), 4, 4, EVIDENCE)["dish_id"]
    with pytest.raises(DomainError) as error:
        buy_rice(conn, dish)
    assert error.value.code == "viability_failed"

    operations.update_kitchen_profile(conn, "oven", None, "available", "tenho forno")
    buy_rice(conn, dish)
    operations.accept_dish(conn, dish)
    assert dish_status(conn, dish)[0] == "accepted"
    assert pantry_stock(conn, "Arroz branco tipo 1") == Decimal("5000")  # purchases never mutate pantry_stock


def test_rejected_dish_cannot_be_accepted(conn):
    viable_profile(conn)
    dish = operations.register_candidate_dish(conn, make_recipe(RICE), 4, 4, EVIDENCE)["dish_id"]
    operations.reject_candidate_dish(conn, dish, "não gosta de fritura", EVIDENCE)
    assert dish_status(conn, dish) == ("rejected", "não gosta de fritura")
    with pytest.raises(DomainError) as error:
        operations.accept_dish(conn, dish)
    assert error.value.code == "not_candidate"


def test_price_scenario_needs_an_accepted_dish(conn):
    dish = operations.register_candidate_dish(conn, make_recipe(RICE), 4, 4, EVIDENCE)["dish_id"]
    with pytest.raises(DomainError) as error:
        operations.select_price_scenario(conn, dish, "0.35")
    assert error.value.code == "not_accepted"


def test_invalid_recipe_is_refused(conn):
    recipe = make_recipe(RICE)
    del recipe["ingredients"]
    with pytest.raises(DomainError) as error:
        operations.register_candidate_dish(conn, recipe, 4, 4, EVIDENCE)
    assert error.value.code == "invalid_recipe"


@pytest.mark.parametrize("yield_portions, launch_batch_portions", [(0, 4), (4, 0)])
def test_non_positive_portions_are_refused(conn, yield_portions, launch_batch_portions):
    with pytest.raises(DomainError) as error:
        operations.register_candidate_dish(conn, make_recipe(RICE), yield_portions, launch_batch_portions, EVIDENCE)
    assert error.value.code == "invalid_portions"


def launch_batch(conn, dish_id):
    return conn.execute("SELECT launch_batch_portions FROM dishes WHERE id = %s", (dish_id,)).fetchone()[0]


def test_a_candidate_launch_batch_can_change_with_her_words(conn):
    # PLAN.md open question 11: in Loop 3 scenario 02 she chose fewer portions to fit the budget and recipe_expert had to
    # register a second candidate of the same recipe, leaving the first as an orphan.
    dish = operations.register_candidate_dish(conn, make_recipe(RICE), 4, 20, EVIDENCE)["dish_id"]
    result = operations.set_launch_batch_portions(conn, dish, 10, "vou fazer só 10 porções então")
    assert result["dish_id"] == dish and result["launch_batch_portions"] == 10 and "pantry_match" in result
    assert launch_batch(conn, dish) == 10


def test_an_accepted_dish_keeps_its_launch_batch(conn):
    viable_profile(conn)
    dish = operations.register_candidate_dish(conn, make_recipe(RICE), 4, 4, EVIDENCE)["dish_id"]
    operations.accept_dish(conn, dish)
    with pytest.raises(DomainError) as error:
        operations.set_launch_batch_portions(conn, dish, 8, "quero 8")
    assert error.value.code == "not_candidate" and launch_batch(conn, dish) == 4


def test_launch_batch_must_be_a_positive_integer(conn):
    dish = operations.register_candidate_dish(conn, make_recipe(RICE), 4, 4, EVIDENCE)["dish_id"]
    for portions in (0, -2, 2.5):
        with pytest.raises(DomainError) as error:
            operations.set_launch_batch_portions(conn, dish, portions, "quero mudar")
        assert error.value.code == "invalid_portions"
    assert launch_batch(conn, dish) == 4


def test_a_to_taste_ingredient_missing_from_the_pantry_lowers_the_coverage(conn):
    # Smoke trial 01 (2026-09-13): cebola, alho, tomate, sal and pimenta-do-reino "a gosto" were left out of the coverage,
    # so a recipe that still needed pimenta-do-reino was shown as "Cobertura da despensa: 100%", and the owner, who wanted a
    # pantry-only dish, accepted it and bought the pepper.
    viable_profile(conn)
    in_pantry = make_recipe([ingredient("Peito de frango", 500, "g"), ingredient("Sal", None, "to_taste")], name="Frango com sal")
    needs_pepper = make_recipe([ingredient("Peito de frango", 500, "g"), ingredient("Pimenta-do-reino", None, "to_taste", None)],
                               name="Frango com pimenta")
    coverage = [operations.check_pantry_match(conn, operations.register_candidate_dish(conn, recipe, 4, 4, EVIDENCE)["dish_id"])
                ["pantry_coverage_pct"] for recipe in (in_pantry, needs_pepper)]
    assert coverage == [100, 50]


def test_registering_the_same_recipe_twice_returns_the_dish_it_already_has(conn):
    # Probe A, scenario 09: the orchestrator's contract client retries a request once when the expert answers off
    # contract (validation.call_with_contract), and the expert had already written the dish. Two "Frango ao molho de
    # açafrão" landed 25 seconds apart, Dona Sálvia rejected the copy to clean up, and "a rejected dish never came back
    # as a new candidate" failed. A write that a retry can repeat has to be idempotent.
    recipe = make_recipe(RICE, name="Frango ao molho de açafrão")
    first = operations.register_candidate_dish(conn, recipe, yield_portions=6, launch_batch_portions=6, evidence=EVIDENCE)
    again = operations.register_candidate_dish(conn, recipe, yield_portions=6, launch_batch_portions=6, evidence=EVIDENCE)
    assert again["dish_id"] == first["dish_id"]
    assert conn.execute("SELECT count(*) FROM dishes WHERE lower(name) = lower(%s)", (recipe["name"],)).fetchone()[0] == 1


def test_a_rejected_recipe_does_not_come_back_as_a_candidate(conn):
    # Same scenario, the other half: once she says no to a dish, registering it again is an error, not a new candidate.
    recipe = make_recipe(RICE, name="Frango ensopado")
    dish_id = operations.register_candidate_dish(conn, recipe, yield_portions=6, launch_batch_portions=6, evidence=EVIDENCE)["dish_id"]
    operations.reject_candidate_dish(conn, dish_id, reason="fica aquele caldo todo", evidence=EVIDENCE)
    with pytest.raises(DomainError) as error:
        operations.register_candidate_dish(conn, recipe, yield_portions=6, launch_batch_portions=6, evidence=EVIDENCE)
    assert error.value.code == "dish_rejected"
