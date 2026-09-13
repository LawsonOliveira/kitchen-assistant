"""PL9 lever 5 in the agents' versioned config."""

import re
from pathlib import Path

import pytest

AGENTS = Path(__file__).resolve().parents[2] / "agents"


@pytest.mark.parametrize("agent", ["fifi", "recipe_expert", "cost_expert", "marketing_expert", "researcher"])
def test_no_agent_offers_the_todo_planner(agent):
    # Live eval trial: recipe_expert called todo_list 12 times; each call is a model round trip that plans nothing.
    disabled = re.search(r"^\s*disabled_toolsets:\s*\[([^\]]*)\]", (AGENTS / agent / "config.yaml").read_text(), flags=re.M)
    assert disabled and "todo" in [name.strip() for name in disabled.group(1).split(",")]


def test_the_orchestrator_is_dona_salvia_and_greets_with_the_owners_words():
    # PL2/PL3 (owner, 2026-09-13): "fifi" becomes "orchestrator" in code; the persona is Dona Sálvia, greeting
    # "Olá, sou a Sálvia, como posso te ajudar hoje? 🌿".
    orchestrator = AGENTS / "orchestrator"
    skin = (orchestrator / "skins" / "dona-salvia.yaml").read_text()
    assert re.search(r"^name: dona-salvia$", skin, flags=re.M) and "agent_name: Dona Sálvia" in skin
    assert 'welcome: "Olá, sou a Sálvia, como posso te ajudar hoje? 🌿"' in skin
    assert re.search(r"^\s*skin: dona-salvia\b", (orchestrator / "config.yaml").read_text(), flags=re.M)
    assert "Olá, sou a Sálvia, como posso te ajudar hoje? 🌿" in (orchestrator / "SOUL.md").read_text()
    assert not any(path.name == "fifi" for path in AGENTS.iterdir())
