import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
REAL_WORKBOOK = REPO_ROOT / "data" / "despensa_dona_maria.xlsx"
TEST_DATABASE = "sabor_test"
EVIDENCE = "Dona Maria disse na conversa"


def _read_dotenv() -> dict:
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return {}
    pairs = (line.split("=", 1) for line in env_file.read_text().splitlines() if "=" in line and not line.startswith("#"))
    return {key.strip(): value.strip() for key, value in pairs}


def live_dsn() -> str:
    """DSN of the running compose app database (the one `make up` seeds)."""
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    dotenv = _read_dotenv()
    password = os.environ.get("POSTGRES_PASSWORD") or dotenv.get("POSTGRES_PASSWORD")
    assert password, "POSTGRES_PASSWORD missing from environment and .env"
    port = os.environ.get("POSTGRES_HOST_PORT") or dotenv.get("POSTGRES_HOST_PORT") or "55432"
    return f"postgresql://sabor:{password}@127.0.0.1:{port}/sabor"


@pytest.fixture
def live_conn():
    with psycopg.connect(live_dsn()) as conn:
        conn.read_only = True
        yield conn


@pytest.fixture
def conn():
    """A fresh `sabor_test` database with migrations and the real workbook seeded — never the live one."""
    from costs_mcp import db
    from costs_mcp.pantry_import import seed_from_workbook

    admin_dsn = live_dsn()
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DATABASE} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DATABASE}")
    try:
        test_dsn = urlunsplit(urlsplit(admin_dsn)._replace(path=f"/{TEST_DATABASE}"))
        with psycopg.connect(test_dsn) as test_conn:
            db.apply_migrations(test_conn)
            seed_from_workbook(test_conn, REAL_WORKBOOK)
            yield test_conn
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(f"DROP DATABASE IF EXISTS {TEST_DATABASE} WITH (FORCE)")


def ingredient(name, quantity, unit, pantry_match="same"):
    return {"name": name, "quantity": quantity, "unit": unit, "pantry_match": name if pantry_match == "same" else pantry_match}


def make_recipe(ingredients, requirements=(), prep_time_minutes=30, yield_portions=4, name="Prato teste"):
    return {
        "name": name,
        "source_url": "https://example.com/receita",
        "yield_portions": yield_portions,
        "prep_time_minutes": prep_time_minutes,
        "ingredients": list(ingredients),
        "requirements": list(requirements),
    }


def reference_recipe():
    """PLAN.md reference dish: yield 4, CMV per portion 2.7159625."""
    return make_recipe(
        [
            ingredient("Arroz branco tipo 1", 400, "g"),
            ingredient("Peito de frango", 600, "g"),
            ingredient("Alho", 10, "g"),
            ingredient("Óleo de soja", 30, "ml"),
            ingredient("Sal", 1, "pinch"),
        ],
        requirements=["stove_burners>=2"],
        prep_time_minutes=45,
        name="Arroz com frango",
    )


def viable_profile(conn, **extra_available):
    """A kitchen that satisfies the parametric keys used by the tests."""
    from costs_mcp import operations

    operations.update_kitchen_profile(conn, "stove_burners", "4", "available", EVIDENCE)
    operations.update_kitchen_profile(conn, "max_batch_time_minutes", "600", "available", EVIDENCE)
    operations.update_kitchen_profile(conn, "fridge_space_liters", "500", "available", EVIDENCE)
    for key in extra_available:
        operations.update_kitchen_profile(conn, key, None, "available", EVIDENCE)


def current_price(conn, name):
    return conn.execute(
        "SELECT p.total_price_paid FROM current_ingredient_prices p JOIN ingredients i ON i.id = p.ingredient_id"
        " WHERE i.name = %s",
        (name,),
    ).fetchone()[0]


def pantry_stock(conn, name):
    return conn.execute(
        "SELECT s.quantity_base FROM pantry_stock s JOIN ingredients i ON i.id = s.ingredient_id WHERE i.name = %s",
        (name,),
    ).fetchone()[0]
