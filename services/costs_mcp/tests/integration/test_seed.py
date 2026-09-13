"""Seed of the live app database after `make up` (Loop 1: full validation replaces the Loop 0 baseline)."""

import subprocess
from decimal import Decimal

from conftest import REPO_ROOT


def test_seed_loads_every_ingredient(live_conn):
    assert live_conn.execute("SELECT count(*) FROM ingredients").fetchone()[0] == 37


def test_seed_skips_nothing():
    logs = subprocess.run(
        ["docker", "compose", "logs", "--no-log-prefix", "costs-mcp"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    assert "seed skipped" not in logs


def test_seed_converts_composite_units(live_conn):
    capers = live_conn.execute(
        "SELECT i.base_unit, s.quantity_base, p.quantity_purchased_base, p.total_price_paid"
        " FROM ingredients i JOIN pantry_stock s ON s.ingredient_id = i.id"
        " JOIN current_ingredient_prices p ON p.ingredient_id = i.id WHERE i.name = 'Alcaparras'"
    ).fetchone()
    assert capers == ("g", Decimal("2000"), Decimal("2000"), Decimal("82.00"))
    topping = live_conn.execute(
        "SELECT i.base_unit, p.total_price_paid FROM ingredients i"
        " JOIN current_ingredient_prices p ON p.ingredient_id = i.id WHERE i.name = 'Cobertura de chocolate'"
    ).fetchone()
    assert topping == ("unit", Decimal("79.90"))
