import unicodedata
from decimal import Decimal

import pytest
from conftest import REAL_WORKBOOK, real_rows

from kitchen_ledger.pantry_import import PantryImportError, diff, load_records


def _codes(error: PantryImportError) -> set[str]:
    return {item["code"] for item in error.errors}


def test_real_workbook_loads_all_37_ingredients():
    records = {record.name: record for record in load_records(REAL_WORKBOOK)}
    assert len(records) == 37

    rice = records["Arroz branco tipo 1"]
    assert (rice.base_unit, rice.stock_base, rice.quantity_purchased_base) == ("g", Decimal("5000"), Decimal("5000"))
    assert (rice.total_price_paid, rice.purchase_unit_label) == (Decimal("24.90"), "5 kg")

    capers = records["Alcaparras"]
    assert (capers.base_unit, capers.stock_base, capers.total_price_paid) == ("g", Decimal("2000"), Decimal("82.00"))
    assert capers.purchase_unit_label == "1 balde 2kg"

    olive_oil = records["Azeite de oliva extra virgem"]
    assert (olive_oil.base_unit, olive_oil.quantity_purchased_base) == ("ml", Decimal("500"))

    topping = records["Cobertura de chocolate"]
    assert (topping.base_unit, topping.total_price_paid) == ("unit", Decimal("79.90"))  # float artifact accepted


def test_names_match_after_strip_and_nfc(make_workbook):
    decomposed = unicodedata.normalize("NFD", "Açúcar")
    path = make_workbook(despensa=[("Açúcar ", 1, "kg")], precos=[(decomposed, 1, "kg", 4.28)])
    assert [record.name for record in load_records(path)] == ["Açúcar"]


@pytest.mark.parametrize(
    "despensa, precos, code",
    [
        ([("Tomate", 2, "kg")], [], "name_in_one_sheet"),
        ([], [("Tomate", 2, "kg", 16)], "name_in_one_sheet"),
        ([("Tomate", -2, "kg")], [("Tomate", 2, "kg", 16)], "non_positive_quantity"),
        ([("Tomate", 2, "kg")], [("Tomate", 0, "kg", 16)], "non_positive_quantity"),
        ([("Tomate", 2, "kg")], [("Tomate", 2, "kg", 79.905)], "non_cent_price"),
        ([("Tomate", 2, "xícara")], [("Tomate", 2, "xícara", 16)], "unknown_unit"),
        ([("Leite integral", 2, "kg")], [("Leite integral", 2, "L", 10)], "incompatible_units"),
    ],
)
def test_invalid_rows_fail_with_a_named_error(make_workbook, despensa, precos, code):
    with pytest.raises(PantryImportError) as error:
        load_records(make_workbook(despensa=despensa, precos=precos))
    assert code in _codes(error.value)


def test_missing_sheet_fails(make_workbook):
    with pytest.raises(PantryImportError) as error:
        load_records(make_workbook(despensa=[("Tomate", 2, "kg")], sheets=("Despensa",)))
    assert "missing_sheet" in _codes(error.value)


def test_missing_column_fails(make_workbook):
    header = ("Ingrediente", "Quantidade comprada", "Unidade")
    with pytest.raises(PantryImportError) as error:
        load_records(make_workbook(despensa=[("Tomate", 2, "kg")], precos=[("Tomate", 2, "kg")], precos_header=header))
    assert "missing_column" in _codes(error.value)


def test_all_errors_are_reported_together(make_workbook):
    path = make_workbook(
        despensa=[("Tomate", -2, "kg"), ("Cebola", 1, "kg")],
        precos=[("Tomate", 2, "kg", 16), ("Cebola", 1, "kg", 4.001)],
    )
    with pytest.raises(PantryImportError) as error:
        load_records(path)
    assert {"non_positive_quantity", "non_cent_price"} <= _codes(error.value)


def test_diff_lists_exactly_the_changed_price(make_workbook):
    precos = [(name, qty, unit, 20 if name == "Tomate" else price) for name, qty, unit, price in real_rows("Precos")]
    changed = load_records(make_workbook(despensa=real_rows("Despensa"), precos=precos))
    result = diff(load_records(REAL_WORKBOOK), changed)
    assert result["added"] == [] and result["removed"] == []
    assert [item["name"] for item in result["changed"]] == ["Tomate"]
    assert result["changed"][0]["fields"]["total_price_paid"] == ["16.00", "20.00"]
    # Full run 20260913-192309, scenario 08 (all three trials): Dona Sálvia read the diff and told the owner the new
    # price, but no field of the diff was a display string, so the output verifier called every "R$" invented and
    # answered with the scope message instead.
    assert result["changed"][0]["display"] == "Tomate: preço pago de R$ 16,00 para R$ 20,00"
