"""sabor_guardrails wired into Hermes on fifi: the Confirmar click reaches the ledger through the hook Hermes fires for
clarify (open question 10). clarify is an inline agent tool, so Hermes runs pre_tool_call and post_tool_call for it but
never transform_tool_result (agent/inline_tool_executors.py in the pinned image)."""

import json

import pytest

import sabor_guardrails
from sabor_guardrails.tool_policy import CLICK_REQUIRED_MESSAGE

CONFIRMATION = {"choice": "Confirmar", "summary": "Fixar o preço em R$ 9,90"}
CLARIFY_RESULT = json.dumps({"responses": [{"question": "Fixar o preço em R$ 9,90?", "choices_offered": ["Confirmar", "Cancelar"],
                                            "user_response": "Confirmar"}]}, ensure_ascii=False)


class FakeContext:
    def __init__(self):
        self.hooks, self.middleware, self.llm = {}, {}, None

    def register_hook(self, name, callback):
        self.hooks.setdefault(name, []).append(callback)

    def register_middleware(self, name, callback):
        self.middleware.setdefault(name, []).append(callback)


def fire(ctx, hook, **kwargs):
    return [callback(**kwargs) for callback in ctx.hooks.get(hook, [])]


@pytest.fixture
def fifi(monkeypatch):
    monkeypatch.setenv("SABOR_AGENT_ROLE", "fifi")
    monkeypatch.setenv("SABOR_GUARD_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("SABOR_TURN_COST_CAP_USD", "5.00")
    ctx = FakeContext()
    sabor_guardrails.register(ctx)
    return ctx


def ask_with_click(ctx, session_id="s1"):
    return fire(ctx, "pre_tool_call", tool_name="ask_cost_expert", session_id=session_id,
                args={"task": "select_price_scenario", "payload": {"dish_id": 2}, "owner_confirmation": CONFIRMATION})


def test_a_confirmar_seen_by_post_tool_call_lets_one_click_required_request_through(fifi):
    fire(fifi, "post_tool_call", tool_name="clarify", args={}, result=CLARIFY_RESULT, session_id="s1")
    assert ask_with_click(fifi) == [None]
    assert ask_with_click(fifi) == [{"action": "block", "message": CLICK_REQUIRED_MESSAGE}]


def test_without_a_clarify_the_click_required_request_is_blocked(fifi):
    assert ask_with_click(fifi) == [{"action": "block", "message": CLICK_REQUIRED_MESSAGE}]
