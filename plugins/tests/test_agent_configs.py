"""PL9 lever 5 in the agents' versioned config."""

import re
from pathlib import Path

import pytest

AGENTS = Path(__file__).resolve().parents[2] / "agents"


@pytest.mark.parametrize("agent", ["orchestrator", "recipe_expert", "cost_expert", "marketing_expert", "researcher"])
def test_no_agent_offers_the_todo_planner(agent):
    # Live eval trial: recipe_expert called todo_list 12 times; each call is a model round trip that plans nothing.
    disabled = re.search(r"^\s*disabled_toolsets:\s*\[([^\]]*)\]", (AGENTS / agent / "config.yaml").read_text(), flags=re.M)
    assert disabled and "todo" in [name.strip() for name in disabled.group(1).split(",")]


def test_the_orchestrator_is_dona_salvia_and_greets_with_the_owners_words():
    # PL2/PL3 (owner, 2026-09-13): "orchestrator" becomes "orchestrator" in code; the persona is Dona Sálvia, greeting
    # "Olá, sou a Sálvia, como posso te ajudar hoje? 🌿".
    orchestrator = AGENTS / "orchestrator"
    skin = (orchestrator / "skins" / "dona-salvia.yaml").read_text()
    assert re.search(r"^name: dona-salvia$", skin, flags=re.M) and "agent_name: Dona Sálvia" in skin
    assert 'welcome: "Olá, sou a Sálvia, como posso te ajudar hoje? 🌿"' in skin
    assert re.search(r"^\s*skin: dona-salvia\b", (orchestrator / "config.yaml").read_text(), flags=re.M)
    assert "Olá, sou a Sálvia, como posso te ajudar hoje? 🌿" in (orchestrator / "SOUL.md").read_text()
    assert not any(path.name == "fifi" for path in AGENTS.iterdir())


@pytest.mark.parametrize("skill", sorted(AGENTS.glob("*/skills/*/SKILL.md")), ids=lambda path: f"{path.parts[-4]}/{path.parts[-2]}")
def test_every_file_a_skill_points_to_can_be_opened_from_the_skill(skill):
    # Full run, scenario 01 trial 2: recipe-normalization named `contracts/recipe.schema.json`, which skill_view cannot open
    # (it is not in the skill); recipe_expert kept looking for it — skills_list, skill_manage, then `research` with the
    # placeholder items "__unused__" and "dummy" — and registering the owner's own recipe took 17 minutes.
    referenced = re.findall(r"`([\w./-]+\.(?:json|md|yaml|py))`", skill.read_text())
    assert [path for path in referenced if not (skill.parent / path).exists()] == []


def test_a_measure_is_asked_of_the_owner_before_it_is_researched():
    # Full run 20260913-192309, scenario 06 (all three trials): Dona Sálvia asked her to confirm a web estimate of 105 g
    # or 150 g for the chocolate bar she buys, priced the dish from it, and her own answer (1 kg) came later or never.
    orchestrator = (AGENTS / "orchestrator" / "SOUL.md").read_text()
    rule = next(line for line in orchestrator.splitlines() if "set_conversion_factor" in line)
    assert "ask her first" in rule and "only when she does not know" in rule
    recipe_expert = (AGENTS / "recipe_expert" / "SOUL.md").read_text()
    measures = next(line for line in recipe_expert.splitlines() if "measure_lookup" in line)
    assert "only when Dona Sálvia says she does not know" in measures


def test_the_price_of_a_missing_item_is_asked_of_the_owner_before_it_is_researched():
    # Full run 20260913-192309, scenario 04 trial 3: the shrimp was bought at the web estimate (R$ 18,99 per 200 g), the
    # shortfall became R$ 123,88 and the budget raise broke the R$ 100,00 cap — her own price (R$ 60,00 the kilo) was
    # never asked for.
    rule = next(line for line in (AGENTS / "orchestrator" / "SOUL.md").read_text().splitlines() if "price_missing_item" in line)
    assert "ask her first" in rule and "only when she does not know" in rule
