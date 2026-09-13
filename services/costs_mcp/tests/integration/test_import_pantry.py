from decimal import Decimal

import openpyxl
import pytest
from conftest import REAL_WORKBOOK, current_price

from costs_mcp import operations
from costs_mcp.operations import DomainError


def modified_workbook(path, tomato_price=None, drop_sheet=None):
    workbook = openpyxl.load_workbook(REAL_WORKBOOK)
    if tomato_price is not None:
        for row in workbook["Precos"].iter_rows(min_row=2):
            if row[0].value == "Tomate":
                row[3].value = tomato_price
    if drop_sheet:
        workbook.remove(workbook[drop_sheet])
    workbook.save(path)
    return path


def import_status(conn, import_id):
    return conn.execute("SELECT status FROM pantry_imports WHERE id = %s", (import_id,)).fetchone()[0]


@pytest.mark.parametrize("make_path", [
    lambda tmp: "/etc/passwd",
    lambda tmp: str(tmp / ".." / "outside.xlsx"),
])
def test_paths_outside_the_import_dir_are_refused(conn, tmp_path, make_path):
    with pytest.raises(DomainError) as error:
        operations.import_pantry(conn, tmp_path, file_path=make_path(tmp_path))
    assert error.value.code == "invalid_import_path"


def test_symlink_escaping_the_import_dir_is_refused(conn, tmp_path):
    link = tmp_path / "despensa.xlsx"
    link.symlink_to(REAL_WORKBOOK)
    with pytest.raises(DomainError) as error:
        operations.import_pantry(conn, tmp_path, file_path=str(link))
    assert error.value.code == "invalid_import_path"


def test_wrong_extension_or_oversized_file_is_refused(conn, tmp_path):
    text_file = tmp_path / "despensa.txt"
    text_file.write_text("not a workbook")
    big_file = tmp_path / "big.xlsx"
    big_file.write_bytes(b"0" * 1_100_000)
    for path in (text_file, big_file):
        with pytest.raises(DomainError) as error:
            operations.import_pantry(conn, tmp_path, file_path=str(path))
        assert error.value.code == "invalid_import_path"


def test_preview_shows_the_diff_and_apply_changes_state(conn, tmp_path):
    path = modified_workbook(tmp_path / "despensa.xlsx", tomato_price=20)
    preview = operations.import_pantry(conn, tmp_path, file_path=str(path))
    assert [item["name"] for item in preview["diff"]["changed"]] == ["Tomate"]
    assert import_status(conn, preview["import_id"]) == "previewed"
    assert current_price(conn, "Tomate") == Decimal("16.00")  # preview changes nothing

    operations.import_pantry(conn, tmp_path, import_id=preview["import_id"], apply=True)
    assert current_price(conn, "Tomate") == Decimal("20.00")
    assert import_status(conn, preview["import_id"]) == "applied"


def test_apply_needs_a_previewed_import(conn, tmp_path):
    with pytest.raises(DomainError) as error:
        operations.import_pantry(conn, tmp_path, import_id=999, apply=True)
    assert error.value.code == "unknown_import"

    path = modified_workbook(tmp_path / "despensa.xlsx", tomato_price=20)
    preview = operations.import_pantry(conn, tmp_path, file_path=str(path))
    operations.import_pantry(conn, tmp_path, import_id=preview["import_id"], apply=True)
    with pytest.raises(DomainError) as error:
        operations.import_pantry(conn, tmp_path, import_id=preview["import_id"], apply=True)
    assert error.value.code == "unknown_import"


def test_invalid_workbook_is_reported_and_changes_nothing(conn, tmp_path):
    path = modified_workbook(tmp_path / "despensa.xlsx", drop_sheet="Precos")
    with pytest.raises(DomainError) as error:
        operations.import_pantry(conn, tmp_path, file_path=str(path))
    assert error.value.code == "invalid_workbook"
    assert "missing_sheet" in {item["code"] for item in error.value.details["errors"]}
    assert current_price(conn, "Tomate") == Decimal("16.00")
