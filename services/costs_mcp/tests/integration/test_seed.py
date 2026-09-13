"""Loop 0 baseline seed: only kg, L and un are parsed; every other unit is skipped loudly."""

import re
import subprocess

from conftest import REPO_ROOT

EXPECTED_SKIPS = {
    ("Alcaparras", "balde 2kg"),
    ("Chantilly", "un 500g"),
    ("Leite ninho em pó", "un 400g"),
    ("Azeite de oliva extra virgem", "un 500ml"),
    ("Aceto balsâmico", "un 500ml"),
    ("Adoçante líquido", "un 100ml"),
}
SKIP_LINE = re.compile(r"ERROR .*seed skipped ingredient=(?P<name>.+?) unit=(?P<unit>.+)$")


def test_seed_loads_simple_units_only(live_conn):
    count = live_conn.execute("SELECT count(*) FROM ingredients").fetchone()[0]
    assert count == 31


def test_seed_logs_each_skipped_row_as_error():
    logs = subprocess.run(
        ["docker", "compose", "logs", "--no-log-prefix", "costs-mcp"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout
    skips = [SKIP_LINE.search(line) for line in logs.splitlines()]
    found = [(m["name"], m["unit"].strip()) for m in skips if m]
    assert len(found) == len(EXPECTED_SKIPS)
    assert set(found) == EXPECTED_SKIPS
