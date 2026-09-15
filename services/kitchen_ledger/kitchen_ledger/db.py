"""Plain SQL, one function per query. Migrations are numbered .sql files applied once each."""

import json
from decimal import Decimal
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

MIGRATIONS = Path(__file__).parent / "migrations"


def connect(dsn: str) -> psycopg.Connection:
    return psycopg.connect(dsn)


def _one(conn, sql, params=()):
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def _all(conn, sql, params=()):
    with conn.cursor(row_factory=dict_row) as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


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


# --- ingredients, stock, prices, conversion factors ------------------------------------------------

def count_ingredients(conn) -> int:
    return conn.execute("SELECT count(*) FROM ingredients").fetchone()[0]


def insert_ingredient(conn, name: str, base_unit: str, kind: str | None = None) -> int:
    if kind is None:
        return conn.execute("INSERT INTO ingredients (name, base_unit) VALUES (%s, %s) RETURNING id", (name, base_unit)).fetchone()[0]
    return conn.execute(
        "INSERT INTO ingredients (name, base_unit, kind) VALUES (%s, %s, %s) RETURNING id", (name, base_unit, kind)
    ).fetchone()[0]


def ingredient_by_name(conn, name: str) -> dict | None:
    return _one(conn, "SELECT id, name, base_unit, kind FROM ingredients WHERE name = %s", (name,))


def insert_pantry_stock(conn, ingredient_id: int, quantity_base: Decimal) -> None:
    conn.execute("INSERT INTO pantry_stock (ingredient_id, quantity_base) VALUES (%s, %s)", (ingredient_id, quantity_base))


def upsert_pantry_stock(conn, ingredient_id: int, quantity_base: Decimal) -> None:
    conn.execute(
        "INSERT INTO pantry_stock (ingredient_id, quantity_base) VALUES (%s, %s)"
        " ON CONFLICT (ingredient_id) DO UPDATE SET quantity_base = EXCLUDED.quantity_base, updated_at = now()",
        (ingredient_id, quantity_base),
    )


def insert_price(conn, ingredient_id: int, total_price_paid: Decimal, quantity_purchased_base: Decimal,
                 purchase_unit_label: str, source: str, source_url: str | None = None, evidence: str | None = None) -> None:
    conn.execute(
        "INSERT INTO ingredient_prices (ingredient_id, total_price_paid, quantity_purchased_base, purchase_unit_label,"
        " source, source_url, evidence) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (ingredient_id, total_price_paid, quantity_purchased_base, purchase_unit_label, source, source_url, evidence),
    )


def supersede_price(conn, ingredient_id: int) -> None:
    conn.execute("UPDATE ingredient_prices SET superseded_at = now() WHERE ingredient_id = %s AND superseded_at IS NULL", (ingredient_id,))


def current_price(conn, ingredient_id: int) -> dict | None:
    return _one(
        conn,
        "SELECT total_price_paid, quantity_purchased_base, purchase_unit_label, source FROM current_ingredient_prices"
        " WHERE ingredient_id = %s",
        (ingredient_id,),
    )


def pantry_rows(conn) -> list[dict]:
    return _all(
        conn,
        "SELECT i.id, i.name, i.kind, i.base_unit, a.quantity_base, p.total_price_paid, p.quantity_purchased_base, p.source"
        " FROM ingredients i JOIN available_stock a ON a.ingredient_id = i.id"
        " LEFT JOIN current_ingredient_prices p ON p.ingredient_id = i.id ORDER BY i.name",
    )


def stocked_records(conn) -> list[dict]:
    """Spreadsheet-shaped view of the current state (ingredients that have a pantry_stock row)."""
    return _all(
        conn,
        "SELECT i.name, i.base_unit, s.quantity_base AS stock_base, p.total_price_paid, p.quantity_purchased_base,"
        " p.purchase_unit_label FROM ingredients i JOIN pantry_stock s ON s.ingredient_id = i.id"
        " JOIN current_ingredient_prices p ON p.ingredient_id = i.id ORDER BY i.name",
    )


def available_stock(conn) -> dict[int, Decimal]:
    return {row["ingredient_id"]: row["quantity_base"] for row in _all(conn, "SELECT ingredient_id, quantity_base FROM available_stock")}


def reservations(conn, dish_id: int) -> dict[int, Decimal]:
    return {row["ingredient_id"]: row["quantity_base"]
            for row in _all(conn, "SELECT ingredient_id, quantity_base FROM dish_reservations WHERE dish_id = %s", (dish_id,))}


def conversion_factors(conn) -> dict[tuple[str, str], tuple[Decimal, str]]:
    rows = _all(
        conn,
        "SELECT i.name, f.measure, f.amount_base, f.amount_base_unit FROM conversion_factors f"
        " JOIN ingredients i ON i.id = f.ingredient_id WHERE f.superseded_at IS NULL",
    )
    return {(row["name"], row["measure"]): (row["amount_base"], row["amount_base_unit"]) for row in rows}


def upsert_cached_recipe(conn, recipe: dict, name_normalized: str, query: str) -> None:
    conn.execute("INSERT INTO recipe_cache (source_url, name, name_normalized, recipe, query) VALUES (%s, %s, %s, %s, %s) "
                 "ON CONFLICT (source_url) DO UPDATE SET name = EXCLUDED.name, name_normalized = EXCLUDED.name_normalized, "
                 "recipe = EXCLUDED.recipe, query = EXCLUDED.query, cached_at = now()",
                 (recipe["source_url"], recipe["name"], name_normalized, Jsonb(recipe), query))


def cached_recipes(conn) -> list[tuple[str, dict]]:
    return conn.execute("SELECT name_normalized, recipe FROM recipe_cache ORDER BY cached_at DESC, id DESC").fetchall()


def measures(conn) -> dict:
    rows = conn.execute("SELECT measure, ingredient_name, amount_base, amount_base_unit, source, source_url FROM measures "
                        "WHERE superseded_at IS NULL").fetchall()
    return {(measure, ingredient): {"amount": amount, "unit": unit, "source": source, "source_url": url}
            for measure, ingredient, amount, unit, source, url in rows}


def replace_measure(conn, measure: str, ingredient_name: str | None, amount_base: Decimal, amount_base_unit: str, source: str,
                    source_url: str | None, evidence: str) -> None:
    conn.execute("UPDATE measures SET superseded_at = now() WHERE measure = %s AND ingredient_name IS NOT DISTINCT FROM %s "
                 "AND superseded_at IS NULL", (measure, ingredient_name))
    conn.execute("INSERT INTO measures (measure, ingredient_name, amount_base, amount_base_unit, source, source_url, evidence) "
                 "VALUES (%s, %s, %s, %s, %s, %s, %s)", (measure, ingredient_name, amount_base, amount_base_unit, source, source_url, evidence))


def replace_conversion_factor(conn, ingredient_id: int, measure: str, amount_base: Decimal, amount_base_unit: str, evidence: str) -> None:
    conn.execute(
        "UPDATE conversion_factors SET superseded_at = now() WHERE ingredient_id = %s AND measure = %s AND superseded_at IS NULL",
        (ingredient_id, measure),
    )
    conn.execute(
        "INSERT INTO conversion_factors (ingredient_id, measure, amount_base, amount_base_unit, evidence) VALUES (%s, %s, %s, %s, %s)",
        (ingredient_id, measure, amount_base, amount_base_unit, evidence),
    )


# --- kitchen profile and dishes ----------------------------------------------------------------------

def kitchen_profile(conn) -> dict[str, dict]:
    return {row["requirement_key"]: row for row in _all(conn, "SELECT requirement_key, status, numeric_value FROM kitchen_profile ORDER BY requirement_key")}


def upsert_kitchen_profile(conn, key: str, status: str, numeric_value: Decimal | None, evidence: str) -> None:
    conn.execute(
        "INSERT INTO kitchen_profile (requirement_key, status, numeric_value, evidence) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (requirement_key) DO UPDATE SET status = EXCLUDED.status, numeric_value = EXCLUDED.numeric_value,"
        " evidence = EXCLUDED.evidence, updated_at = now()",
        (key, status, numeric_value, evidence),
    )


def insert_dish(conn, recipe: dict, yield_portions: int, launch_batch_portions: int, packaging_ingredient_id: int | None,
                evidence: str) -> int:
    return conn.execute(
        "INSERT INTO dishes (name, recipe, source_url, yield_portions, launch_batch_portions, packaging_ingredient_id,"
        " status, evidence) VALUES (%s, %s, %s, %s, %s, %s, 'candidate', %s) RETURNING id",
        (recipe["name"], Jsonb(recipe), recipe["source_url"], yield_portions, launch_batch_portions, packaging_ingredient_id, evidence),
    ).fetchone()[0]


def get_dish(conn, dish_id: int) -> dict | None:
    return _one(conn, "SELECT * FROM dishes WHERE id = %s", (dish_id,))


def dishes(conn, status: str | None = None) -> list[dict]:
    if status is None:
        return _all(conn, "SELECT * FROM dishes ORDER BY id")
    return _all(conn, "SELECT * FROM dishes WHERE status = %s ORDER BY id", (status,))


def reject_dish(conn, dish_id: int, reason: str) -> None:
    conn.execute("UPDATE dishes SET status = 'rejected', rejected_reason = %s, rejected_at = now() WHERE id = %s", (reason, dish_id))


def set_launch_batch_portions(conn, dish_id: int, launch_batch_portions: int) -> None:
    conn.execute("UPDATE dishes SET launch_batch_portions = %s WHERE id = %s", (launch_batch_portions, dish_id))


def accept_dish(conn, dish_id: int) -> None:
    conn.execute("UPDATE dishes SET status = 'accepted', accepted_at = now() WHERE id = %s", (dish_id,))


def select_price_scenario(conn, dish_id: int, target_cmv_pct: Decimal, selected_price: Decimal) -> None:
    conn.execute("UPDATE dishes SET selected_target_cmv_pct = %s, selected_price = %s WHERE id = %s", (target_cmv_pct, selected_price, dish_id))


def set_dish_packaging(conn, dish_id: int, packaging_ingredient_id: int) -> None:
    conn.execute("UPDATE dishes SET packaging_ingredient_id = %s WHERE id = %s", (packaging_ingredient_id, dish_id))


def insert_dish_requirement(conn, dish_id: int, requirement: str, origin: str) -> None:
    conn.execute(
        "INSERT INTO dish_requirements (dish_id, requirement, origin) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
        (dish_id, requirement, origin),
    )


def dish_requirements(conn, dish_id: int) -> list[dict]:
    return _all(
        conn,
        "SELECT requirement, origin, confirmation_status FROM dish_requirements WHERE dish_id = %s ORDER BY origin DESC, requirement",
        (dish_id,),
    )


def confirm_dish_requirement(conn, dish_id: int, requirement: str, status: str, evidence: str) -> int:
    return conn.execute(
        "UPDATE dish_requirements SET confirmation_status = %s, confirmation_evidence = %s, confirmed_at = now()"
        " WHERE dish_id = %s AND requirement = %s",
        (status, evidence, dish_id, requirement),
    ).rowcount


def insert_reservation(conn, dish_id: int, ingredient_id: int, quantity_base: Decimal) -> None:
    conn.execute("INSERT INTO dish_reservations (dish_id, ingredient_id, quantity_base) VALUES (%s, %s, %s)", (dish_id, ingredient_id, quantity_base))


# --- budget, purchases, menu, imports, audit ------------------------------------------------------------

def budget_status(conn) -> dict:
    return _one(conn, "SELECT initial_amount, adjustments_total, purchases_total, remaining FROM budget_status")


def insert_budget_adjustment(conn, delta: Decimal, evidence: str) -> None:
    conn.execute("INSERT INTO budget_adjustments (delta, evidence) VALUES (%s, %s)", (delta, evidence))


def insert_purchase(conn, ingredient_id: int, dish_id: int | None, packages: int, package_quantity_base: Decimal,
                    package_price: Decimal, price_source: str, source_url: str | None, evidence: str) -> None:
    conn.execute(
        "INSERT INTO purchases (ingredient_id, dish_id, packages, package_quantity_base, package_price, price_source,"
        " source_url, evidence) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (ingredient_id, dish_id, packages, package_quantity_base, package_price, price_source, source_url, evidence),
    )


def purchases_with_dishes(conn) -> list[dict]:
    return _all(
        conn,
        "SELECT i.name AS ingredient, i.base_unit, p.packages, p.package_quantity_base, p.package_price, d.name AS dish_name"
        " FROM purchases p JOIN ingredients i ON i.id = p.ingredient_id LEFT JOIN dishes d ON d.id = p.dish_id ORDER BY p.id",
    )


def upsert_menu_copy(conn, dish_id: int, title: str, description: str, evidence: str) -> None:
    conn.execute(
        "INSERT INTO menu_copy (dish_id, title, description, evidence) VALUES (%s, %s, %s, %s)"
        " ON CONFLICT (dish_id) DO UPDATE SET title = EXCLUDED.title, description = EXCLUDED.description,"
        " evidence = EXCLUDED.evidence, updated_at = now()",
        (dish_id, title, description, evidence),
    )


def menu_copy(conn, dish_id: int) -> dict | None:
    return _one(conn, "SELECT title, description FROM menu_copy WHERE dish_id = %s", (dish_id,))


def insert_promotion(conn, dish_id: int, description: str, discount_pct: Decimal, evidence: str) -> int:
    return conn.execute(
        "INSERT INTO promotions (dish_id, description, discount_pct, evidence) VALUES (%s, %s, %s, %s) RETURNING id",
        (dish_id, description, discount_pct, evidence),
    ).fetchone()[0]


def insert_pantry_import(conn, file_path: str, file_sha256: str, diff: dict) -> int:
    return conn.execute(
        "INSERT INTO pantry_imports (file_path, file_sha256, diff, status) VALUES (%s, %s, %s, 'previewed') RETURNING id",
        (file_path, file_sha256, Jsonb(diff)),
    ).fetchone()[0]


def get_pantry_import(conn, import_id: int) -> dict | None:
    return _one(conn, "SELECT id, file_path, file_sha256, status FROM pantry_imports WHERE id = %s", (import_id,))


def mark_pantry_import_applied(conn, import_id: int) -> None:
    conn.execute("UPDATE pantry_imports SET status = 'applied', applied_at = now() WHERE id = %s", (import_id,))


def insert_audit(conn, agent: str, tool: str, args: dict, result, error_code: str | None, trace_id: str | None) -> None:
    conn.execute(
        "INSERT INTO audit_log (agent, tool, args, result, error_code, trace_id) VALUES (%s, %s, %s, %s, %s, %s)",
        (agent, tool, Jsonb(json.loads(json.dumps(args, default=str))), Jsonb(json.loads(json.dumps(result, default=str))),
         error_code, trace_id),
    )
