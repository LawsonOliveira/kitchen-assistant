"""PL6 (owner): household measures live in the database; a measure found on the web waits for her click (like D27)."""

from decimal import Decimal

import pytest
from conftest import EVIDENCE, ingredient, make_recipe, viable_profile

from kitchen_ledger import operations
from kitchen_ledger.operations import DomainError

URL = "https://www.mercado.example/leite-de-coco-200ml"


def coconut_dish(conn):
    viable_profile(conn)
    operations.record_price_quote(conn, "Leite de coco", "food", "200", "ml", "4.50", "owner_confirmed", None, EVIDENCE)
    recipe = make_recipe([ingredient("Arroz branco tipo 1", 400, "g"), ingredient("Leite de coco", 1, "can")])
    return operations.register_candidate_dish(conn, recipe, 4, 4, EVIDENCE)


def coconut_line(conn, dish):
    return next(line for line in operations.compute_dish_cost(conn, dish)["lines"] if line["ingredient"] == "Leite de coco")


def test_the_d23_table_is_seeded_into_the_measures_table(conn):
    rows = conn.execute("SELECT measure, ingredient_name, amount_base, amount_base_unit FROM measures "
                        "WHERE source = 'seed' AND superseded_at IS NULL").fetchall()
    # 16 rows of the D23 table plus the common units of her pantry (migration 005, latency pass).
    assert len(rows) == 28 and ("clove", "Alho", Decimal("5"), "g") in rows


def test_an_unknown_measure_is_a_conversion_to_find(conn):
    assert {"ingredient": "Leite de coco", "measure": "can"} in coconut_dish(conn)["pantry_match"]["conversions_needed"]


def test_a_web_measure_is_stored_but_never_used_in_cmv_until_the_owner_confirms(conn):
    dish = coconut_dish(conn)["dish_id"]
    quote = operations.record_measure_quote(conn, "Leite de coco", "can", "200", "ml", URL, "pesquisa: lata de leite de coco")
    assert quote == {"ingredient": "Leite de coco", "measure": "can", "amount_display": "200 ml", "source": "web_estimate", "source_url": URL}
    with pytest.raises(DomainError) as error:
        operations.compute_dish_cost(conn, dish)
    assert error.value.code == "unconfirmed_measure"
    estimate = {"ingredient": "Leite de coco", "measure": "can", "estimate": {"amount_display": "200 ml", "source_url": URL}}
    assert estimate in operations.check_pantry_match(conn, dish)["conversions_needed"]


def test_the_owner_click_confirms_the_measure_and_the_cost_uses_it(conn):
    dish = coconut_dish(conn)["dish_id"]
    operations.record_measure_quote(conn, "Leite de coco", "can", "200", "ml", URL, "pesquisa")
    assert operations.confirm_measure(conn, "Leite de coco", "can", "Confirmar: 1 lata = 200 ml")["source"] == "owner_confirmed"
    assert coconut_line(conn, dish)["quantity_used_display"] == "200 ml"


def test_her_own_factor_wins_over_any_stored_measure(conn):
    dish = coconut_dish(conn)["dish_id"]
    operations.record_measure_quote(conn, "Leite de coco", "can", "200", "ml", URL, "pesquisa")
    operations.set_conversion_factor(conn, "Leite de coco", "can", "400", "ml", "a lata que eu compro tem 400 ml")
    assert coconut_line(conn, dish)["quantity_used_display"] == "400 ml"


@pytest.mark.parametrize("measure, amount, unit, code", [("bucket", "200", "ml", "unknown_measure"),
                                                         ("can", "0", "ml", "invalid_amount"),
                                                         ("can", "200", "cup", "invalid_unit")])
def test_a_measure_quote_outside_the_vocabulary_or_with_a_bad_amount_is_refused(conn, measure, amount, unit, code):
    with pytest.raises(DomainError) as error:
        operations.record_measure_quote(conn, "Leite de coco", measure, amount, unit, URL, "pesquisa")
    assert error.value.code == code


def test_a_web_estimate_never_replaces_a_seeded_or_confirmed_measure(conn):
    with pytest.raises(DomainError) as error:
        operations.record_measure_quote(conn, "Alho", "clove", "8", "g", URL, "pesquisa")
    assert error.value.code == "measure_already_known"


def test_there_is_nothing_to_confirm_without_a_web_estimate(conn):
    with pytest.raises(DomainError) as error:
        operations.confirm_measure(conn, "Leite de coco", "can", "Confirmar")
    assert error.value.code == "no_measure_estimate"
    # Full run, scenario 01 trial 2: Dona Sálvia asked the owner to confirm the same measure four times because the error
    # did not say what to do instead.
    assert "set_conversion_factor" in str(error.value)


def test_the_common_units_of_her_pantry_need_no_question(conn):
    # Latency pass: every measure missing from the table becomes a question to her and sometimes a web lookup. One
    # medium onion or tomato is a standard weight she can still correct, so it is seeded.
    from kitchen_ledger import db

    measures = db.measures(conn)
    for name in ("Cebola", "Tomate", "Batata", "Ovos", "Peito de frango"):
        assert ("unit", name) in measures, name
        assert measures[("unit", name)]["source"] == "seed"
    assert ("cup", "Feijão carioquinha") in measures
