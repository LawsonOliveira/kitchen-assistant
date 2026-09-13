"""Plain SQL, one function per query. Migrations are numbered .sql files applied once each."""

from decimal import Decimal
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).parent / "migrations"


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn)


def apply_migrations(conn: psycopg.Connection) -> list[int]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_version")}
    newly_applied = []
    for path in sorted(MIGRATIONS.glob("*.sql")):
        version = int(path.name.split("_", 1)[0])
        if version in applied:
            continue
        conn.execute(path.read_text())
        conn.execute("INSERT INTO schema_version (version) VALUES (%s) ON CONFLICT DO NOTHING", (version,))
        newly_applied.append(version)
    conn.commit()
    return newly_applied


def count_ingredients(conn: psycopg.Connection) -> int:
    return conn.execute("SELECT count(*) FROM ingredients").fetchone()[0]


def insert_ingredient(conn: psycopg.Connection, name: str, base_unit: str) -> int:
    return conn.execute(
        "INSERT INTO ingredients (name, base_unit) VALUES (%s, %s) RETURNING id", (name, base_unit)
    ).fetchone()[0]


def insert_pantry_stock(conn: psycopg.Connection, ingredient_id: int, quantity_base: Decimal) -> None:
    conn.execute(
        "INSERT INTO pantry_stock (ingredient_id, quantity_base) VALUES (%s, %s)", (ingredient_id, quantity_base)
    )


def insert_price(
    conn: psycopg.Connection,
    ingredient_id: int,
    total_price_paid: Decimal,
    quantity_purchased_base: Decimal,
    purchase_unit_label: str,
    source: str,
) -> None:
    conn.execute(
        "INSERT INTO ingredient_prices (ingredient_id, total_price_paid, quantity_purchased_base, purchase_unit_label, source)"
        " VALUES (%s, %s, %s, %s, %s)",
        (ingredient_id, total_price_paid, quantity_purchased_base, purchase_unit_label, source),
    )


def pantry_with_current_prices(conn: psycopg.Connection) -> list[tuple]:
    """(name, base_unit, stock quantity_base, total_price_paid, quantity_purchased_base) per ingredient."""
    return conn.execute(
        "SELECT i.name, i.base_unit, s.quantity_base, p.total_price_paid, p.quantity_purchased_base"
        " FROM ingredients i"
        " LEFT JOIN pantry_stock s ON s.ingredient_id = i.id"
        " LEFT JOIN current_ingredient_prices p ON p.ingredient_id = i.id"
        " ORDER BY i.name"
    ).fetchall()


def ingredient_with_current_price(conn: psycopg.Connection, name: str) -> tuple | None:
    """(base_unit, total_price_paid, quantity_purchased_base) or None when the ingredient does not exist."""
    return conn.execute(
        "SELECT i.base_unit, p.total_price_paid, p.quantity_purchased_base"
        " FROM ingredients i LEFT JOIN current_ingredient_prices p ON p.ingredient_id = i.id"
        " WHERE i.name = %s",
        (name,),
    ).fetchone()
