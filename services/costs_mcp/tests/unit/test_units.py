from decimal import Decimal

import pytest

from costs_mcp.units import IncompatibleUnitsError, NonPositiveQuantityError, UnknownUnitError, parse_unit, to_base


@pytest.mark.parametrize(
    "raw, base_unit, factor",
    [
        ("g", "g", 1),
        ("kg", "g", 1000),
        ("ml", "ml", 1),
        ("l", "ml", 1000),
        ("L", "ml", 1000),
        ("un", "unit", 1),
        ("unit", "unit", 1),
        ("balde 2kg", "g", 2000),
        ("un 500g", "g", 500),
        ("un 400g", "g", 400),
        ("un 500ml", "ml", 500),
        ("un 100ml", "ml", 100),
    ],
)
def test_parse_unit_normalizes_to_base(raw, base_unit, factor):
    spec = parse_unit(raw)
    assert spec.base_unit == base_unit
    assert spec.factor_to_base == Decimal(factor)


def test_composite_unit_keeps_its_container_label():
    assert parse_unit("balde 2kg").package_label == "balde"
    assert parse_unit("kg").package_label is None


@pytest.mark.parametrize("raw", ["xícara", "", "2kg balde", "un 500", "pacote 1lb", "kgs"])
def test_unknown_unit_fails_loud(raw):
    with pytest.raises(UnknownUnitError):
        parse_unit(raw)


def test_to_base_multiplies_by_the_unit_factor():
    assert to_base(Decimal("1.5"), "kg") == Decimal("1500")
    assert to_base(Decimal("1"), "balde 2kg") == Decimal("2000")
    assert to_base(Decimal("30"), "un") == Decimal("30")


@pytest.mark.parametrize("quantity", [Decimal("0"), Decimal("-1")])
def test_non_positive_quantity_fails_loud(quantity):
    with pytest.raises(NonPositiveQuantityError):
        to_base(quantity, "kg")


def test_expected_base_unit_mismatch_fails_loud():
    with pytest.raises(IncompatibleUnitsError):
        to_base(Decimal("1"), "kg", expected_base_unit="ml")
