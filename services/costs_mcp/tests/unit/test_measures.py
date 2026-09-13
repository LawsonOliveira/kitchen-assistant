from decimal import Decimal

import pytest

from costs_mcp.measures import MissingConversionError, resolve_measure


def test_ingredient_specific_measure_is_an_estimate():
    assert resolve_measure("Farinha de trigo", "cup", Decimal("1")) == (Decimal("120"), "g", True)


def test_count_multiplies_the_measure():
    assert resolve_measure("Alho", "clove", Decimal("2")) == (Decimal("10"), "g", True)


def test_generic_measure_applies_to_any_ingredient():
    assert resolve_measure("Vinagre", "tablespoon", Decimal("2")) == (Decimal("30"), "ml", True)


def test_small_fixed_amounts_for_pinch_and_to_taste():
    assert resolve_measure("Sal", "pinch", Decimal("1")) == (Decimal("1"), "g", True)
    assert resolve_measure("Pimenta", "to_taste", Decimal("1")) == (Decimal("1"), "g", True)


def test_ingredient_specific_can():
    assert resolve_measure("Creme de leite", "can", Decimal("1")) == (Decimal("200"), "g", True)


@pytest.mark.parametrize(
    "ingredient, measure",
    [("Cobertura de chocolate", "can"), ("Qualquer coisa", "can"), ("Qualquer coisa", "package"), ("Farinha de trigo", "package")],
)
def test_measure_without_table_entry_fails_loud(ingredient, measure):
    with pytest.raises(MissingConversionError) as error:
        resolve_measure(ingredient, measure, Decimal("1"))
    assert (error.value.ingredient, error.value.measure) == (ingredient, measure)


def test_owner_factor_overrides_the_table_and_is_not_an_estimate():
    owner_factors = {("Farinha de trigo", "cup"): (Decimal("140"), "g")}
    assert resolve_measure("Farinha de trigo", "cup", Decimal("1"), owner_factors) == (Decimal("140"), "g", False)


def test_owner_factor_covers_a_missing_entry():
    owner_factors = {("Leite condensado", "package"): (Decimal("395"), "g")}
    assert resolve_measure("Leite condensado", "package", Decimal("2"), owner_factors) == (Decimal("790"), "g", False)
