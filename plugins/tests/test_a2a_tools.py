"""orchestrator's ask_* tools: tasks come from the expert contracts; a request outside the contract is never sent (D6, D14)."""

import json
from pathlib import Path

import pytest

import kitchen_a2a
from kitchen_a2a import validation

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts" / "experts"
CONFIRMATION = {"choice": "Confirmar", "summary": "Comprar 1 pacote de 2 kg de tomate por R$ 16,00"}
PURCHASE = {"dish_id": 5, "ingredient": "Tomate", "kind": "food", "packages": 1, "package_quantity": 2, "package_unit": "kg",
            "package_price": "16.00", "price_source": "owner_confirmed", "source_url": None}


class FakeContext:
    def __init__(self):
        self.tools = {}

    def register_tool(self, name, toolset, handler, description, schema):
        self.tools[name] = {"handler": handler, "schema": schema}

    def register_hook(self, name, callback):
        pass

    def register_system_prompt_section(self, section_id, content):
        pass


@pytest.fixture
def orchestrator_tools(monkeypatch):
    monkeypatch.setenv("KITCHEN_AGENT_ROLE", "orchestrator")
    monkeypatch.setenv("KITCHEN_A2A_TOKEN", "token-orchestrator")
    ctx = FakeContext()
    kitchen_a2a.register(ctx)
    return ctx.tools


@pytest.mark.parametrize("tool, expert", [("ask_recipe_expert", "recipe_expert"), ("ask_cost_expert", "cost_expert"),
                                          ("ask_marketing_expert", "marketing_expert")])
def test_each_ask_tool_offers_exactly_the_tasks_of_its_contract(orchestrator_tools, tool, expert):
    contract = json.loads((CONTRACTS / f"{expert}.request.json").read_text())
    offered = orchestrator_tools[tool]["schema"]["parameters"]["properties"]["task"]["enum"]
    assert offered == contract["properties"]["task"]["enum"] and len(offered) >= 2


def test_a_click_required_task_without_the_click_is_never_sent(orchestrator_tools, monkeypatch):
    def must_not_send(*args, **kwargs):
        raise AssertionError("request sent without owner_confirmation")

    monkeypatch.setattr(validation, "call_with_contract", must_not_send)
    reply = json.loads(orchestrator_tools["ask_cost_expert"]["handler"]({"task": "register_purchase", "payload": PURCHASE}))
    assert reply["error"]["code"] == "invalid_request"


def test_the_click_travels_with_the_request(orchestrator_tools, monkeypatch):
    sent = {}

    def fake_send(peer_url, token, request, response_schema, timeout_s):
        sent.update(request=request, peer_url=peer_url)
        return {"result": {"budget_remaining_display": "R$ 64,00"}, "questions_for_owner": [], "cost_usd_spent": 0.0}

    monkeypatch.setattr(validation, "call_with_contract", fake_send)
    reply = json.loads(orchestrator_tools["ask_cost_expert"]["handler"](
        {"task": "register_purchase", "payload": PURCHASE, "owner_confirmation": CONFIRMATION}))
    assert reply["result"]["budget_remaining_display"] == "R$ 64,00"
    assert sent["request"]["owner_confirmation"] == CONFIRMATION and sent["peer_url"] == "http://cost-expert:9900/"


def test_the_task_guide_shows_short_enum_values(orchestrator_tools):
    # Loop 3 scenario 02: orchestrator sent status "confirmed" twice because the guide listed only field names.
    guide = orchestrator_tools["ask_recipe_expert"]["schema"]["description"]
    assert "status: available|unavailable" in guide and "kind: food|packaging" in orchestrator_tools["ask_cost_expert"]["schema"]["description"]


def test_research_refuses_placeholder_items_before_the_researcher_is_asked():
    # Full run trials 2 (2026-09-13): recipe_expert called research with items ["__unused__"], ["dummy"] and
    # ["placeholder"]; the researcher answered in prose, the contract retry answered in prose again, and every round trip
    # cost a model call on both sides.
    for items in (["placeholder"], ["dummy"], ["__unused__"], []):
        reply = json.loads(kitchen_a2a._research({"task_type": "recipe_search", "items": items}))
        assert reply["error"]["code"] == "invalid_request", items
        assert "placeholder" in reply["error"]["message"], items
