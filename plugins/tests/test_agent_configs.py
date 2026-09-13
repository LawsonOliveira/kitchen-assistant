"""PL9 levers 3 and 5 in the agents' versioned config."""

import re
from pathlib import Path

import pytest

AGENTS = Path(__file__).resolve().parents[2] / "agents"


@pytest.mark.parametrize("agent", ["fifi", "recipe_expert", "cost_expert", "marketing_expert", "researcher"])
def test_no_agent_offers_the_todo_planner(agent):
    # Live eval trial: recipe_expert called todo_list 12 times; each call is a model round trip that plans nothing.
    disabled = re.search(r"^\s*disabled_toolsets:\s*\[([^\]]*)\]", (AGENTS / agent / "config.yaml").read_text(), flags=re.M)
    assert disabled and "todo" in [name.strip() for name in disabled.group(1).split(",")]


def test_research_children_have_an_iteration_cap():
    # Live eval trial: 120 Haiku calls for a handful of research children; a child needs search, extract and the answer.
    match = re.search(r"^delegation:\n(?:[ ]+.*\n)*?[ ]+max_iterations:\s*(\d+)", (AGENTS / "researcher" / "config.yaml").read_text(), flags=re.M)
    assert match and int(match.group(1)) <= 10
