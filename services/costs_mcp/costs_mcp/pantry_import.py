"""Spreadsheet seed — Loop 0 baseline: only kg, L and un are parsed; any other unit is skipped loudly.

Loop 1 replaces this with full validation (composite units, all errors together, startup fails).
"""

import logging
from decimal import Decimal
from pathlib import Path

import openpyxl
import psycopg

from costs_mcp import db

log = logging.getLogger("costs_mcp.seed")

SIMPLE_UNITS = {"kg": ("g", Decimal(1000)), "L": ("ml", Decimal(1000)), "un": ("unit", Decimal(1))}
CENT = Decimal("0.01")


def _sheet_rows(workbook, sheet: str) -> list[dict]:
    header, *rows = workbook[sheet].iter_rows(values_only=True)
    return [dict(zip(header, row)) for row in rows if any(value is not None for value in row)]


def _whole_cents(value, name: str) -> Decimal:
    exact = Decimal(str(value))
    cents = exact.quantize(CENT)
    if abs(exact - cents) > Decimal("0.000001"):
        raise ValueError(f"price of {name!r} is not a whole number of cents: {value}")
    return cents


def seed_from_workbook(conn: psycopg.Connection, path: Path) -> int:
    """Seed an empty database from the workbook; returns how many ingredients were loaded."""
    if db.count_ingredients(conn):
        return 0
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    prices = {row["Ingrediente"].strip(): row for row in _sheet_rows(workbook, "Precos")}
    loaded = 0
    for row in _sheet_rows(workbook, "Despensa"):
        name, unit = row["Ingrediente"].strip(), str(row["Unidade"]).strip()
        price = prices[name]  # an ingredient without a price row has no unit cost: fail loud
        if unit not in SIMPLE_UNITS or str(price["Unidade"]).strip() != unit:
            log.error("seed skipped ingredient=%s unit=%s", name, unit)
            continue
        base_unit, factor = SIMPLE_UNITS[unit]
        ingredient_id = db.insert_ingredient(conn, name, base_unit)
        db.insert_pantry_stock(conn, ingredient_id, Decimal(str(row["Quantidade em estoque"])) * factor)
        purchased = Decimal(str(price["Quantidade comprada"]))
        db.insert_price(
            conn,
            ingredient_id,
            _whole_cents(price["Preço total pago (R$)"], name),
            purchased * factor,
            f"{purchased} {unit}",
            "spreadsheet",
        )
        loaded += 1
    conn.commit()
    return loaded
