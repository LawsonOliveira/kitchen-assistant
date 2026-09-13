import os
from pathlib import Path

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]


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
