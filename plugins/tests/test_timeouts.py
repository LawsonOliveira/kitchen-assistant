"""Nested timeouts (PLAN.md D38, correction C35): each waiting layer outlives the one it waits for."""

import re
from pathlib import Path

import kitchen_a2a

ORCHESTRATOR_CONFIG = Path(__file__).resolve().parents[2] / "agents" / "orchestrator" / "config.yaml"


def _seconds(key: str) -> float:
    match = re.search(rf"^\s*{key}:\s*([0-9.]+)", ORCHESTRATOR_CONFIG.read_text(), flags=re.M)
    assert match, f"{key} is not set in agents/orchestrator/config.yaml"
    return float(match.group(1))


def test_orchestrator_lets_an_expert_call_run_as_long_as_its_a2a_client_waits():
    # Live eval trial: Hermes' default sequential tool deadline (420 s) cut ask_recipe_expert while kitchen_a2a's client
    # still waited 480 s for the expert, so the research finished for nobody.
    expert_client = max(timeout for peer, (url, timeout) in kitchen_a2a.PEERS.items() if peer != "researcher")
    assert expert_client < _seconds("sequential_call") < _seconds("run_budget_seconds")
