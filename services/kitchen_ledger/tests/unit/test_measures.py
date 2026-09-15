from decimal import Decimal

import pytest

from kitchen_ledger.measures import MissingConversionError, UnconfirmedMeasureError, resolve_measure


def row(amount, unit, source="seed", source_url=None):
    return {"amount": Decimal(amount), "unit": unit, "source": source, "source_url": source_url}


# The D23 table as the measures table seeds it (PL6); a subset is enough for the resolution rules.
TABLE = {("cup", "Farinha de trigo"): row("120", "g"), ("tablespoon", None): row("15", "ml"), ("clove", "Alho"): row("5", "g"),
         ("pinch", None): row("1", "g"), ("to_taste", None): row("1", "g"), ("can", "Creme de leite"): row("200", "g")}


def test_ingredient_specific_measure_is_an_estimate():
    assert resolve_measure("Farinha de trigo", "cup", Decimal("1"), table=TABLE) == (Decimal("120"), "g", True)


def test_count_multiplies_the_measure():
    assert resolve_measure("Alho", "clove", Decimal("2"), table=TABLE) == (Decimal("10"), "g", True)


def test_generic_measure_applies_to_any_ingredient():
    assert resolve_measure("Vinagre", "tablespoon", Decimal("2"), table=TABLE) == (Decimal("30"), "ml", True)


def test_small_fixed_amounts_for_pinch_and_to_taste():
    assert resolve_measure("Sal", "pinch", Decimal("1"), table=TABLE) == (Decimal("1"), "g", True)
    assert resolve_measure("Pimenta", "to_taste", Decimal("1"), table=TABLE) == (Decimal("1"), "g", True)


def test_ingredient_specific_can():
    assert resolve_measure("Creme de leite", "can", Decimal("1"), table=TABLE) == (Decimal("200"), "g", True)


@pytest.mark.parametrize(
    "ingredient, measure",
    [("Cobertura de chocolate", "can"), ("Qualquer coisa", "can"), ("Qualquer coisa", "package"), ("Farinha de trigo", "package")],
)
def test_measure_without_table_entry_fails_loud(ingredient, measure):
    with pytest.raises(MissingConversionError) as error:
        resolve_measure(ingredient, measure, Decimal("1"), table=TABLE)
    assert (error.value.ingredient, error.value.measure) == (ingredient, measure)


def test_owner_factor_overrides_the_table_and_is_not_an_estimate():
    owner_factors = {("Farinha de trigo", "cup"): (Decimal("140"), "g")}
    assert resolve_measure("Farinha de trigo", "cup", Decimal("1"), owner_factors, table=TABLE) == (Decimal("140"), "g", False)


def test_owner_factor_covers_a_missing_entry():
    owner_factors = {("Leite condensado", "package"): (Decimal("395"), "g")}
    assert resolve_measure("Leite condensado", "package", Decimal("2"), owner_factors, table=TABLE) == (Decimal("790"), "g", False)


# Loop 3 scenario 02: "óleo a gosto" became a density question because the fixed estimate was always in grams.
@pytest.mark.parametrize(
    "ingredient, measure, base_unit, expected",
    [("Óleo de soja", "to_taste", "ml", (Decimal("1"), "ml", True)),
     ("Azeite de oliva extra virgem", "drizzle", "ml", (Decimal("5"), "ml", True)),
     ("Manteiga", "drizzle", "g", (Decimal("5"), "g", True)),
     ("Sal", "pinch", "g", (Decimal("1"), "g", True)),
     ("Leite integral", "pinch", "ml", (Decimal("1"), "ml", True))],
)
def test_small_fixed_estimates_follow_the_ingredient_base_unit(ingredient, measure, base_unit, expected):
    assert resolve_measure(ingredient, measure, Decimal("1"), base_unit=base_unit, table=TABLE) == expected


# PL6 (owner): a measure found on the web never enters CMV until Dona Maria confirms it, like a price estimate (D27).
def test_a_web_estimate_is_not_usable_until_the_owner_confirms_it():
    url = "https://www.mercado.example/leite-de-coco-200ml"
    table = {**TABLE, ("can", "Leite de coco"): row("200", "ml", "web_estimate", url)}
    with pytest.raises(UnconfirmedMeasureError) as error:
        resolve_measure("Leite de coco", "can", Decimal("1"), table=table)
    assert (error.value.ingredient, error.value.measure, error.value.amount_display, error.value.source_url) == ("Leite de coco", "can", "200 ml", url)


def test_an_owner_confirmed_measure_is_not_an_estimate():
    table = {**TABLE, ("can", "Leite de coco"): row("200", "ml", "owner_confirmed")}
    assert resolve_measure("Leite de coco", "can", Decimal("1"), table=table) == (Decimal("200"), "ml", False)


def test_an_ingredient_specific_row_beats_the_generic_one():
    table = {**TABLE, ("tablespoon", "Manteiga"): row("15", "g")}
    assert resolve_measure("Manteiga", "tablespoon", Decimal("1"), table=table) == (Decimal("15"), "g", True)
