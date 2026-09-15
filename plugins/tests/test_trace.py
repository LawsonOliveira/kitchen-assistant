"""Trace propagation (PLAN.md D32, Loop 5): one trace per owner turn, carried in every A2A request, adopted by the
serving agent and its web children, and passed to kitchen-ledger in the tool arguments."""

import importlib.util
import json
import re
import sys
import types
from pathlib import Path

import pytest

import kitchen_a2a
import kitchen_observability
from kitchen_a2a import validation
from kitchen_observability import emit, trace

PLUGINS = Path(__file__).resolve().parents[1]
TRACE_ID = "0123456789abcdef0123456789abcdef"
PARENT_SPAN_ID = "89abcdef01234567"
INCOMING_TRACE = {"trace_id": TRACE_ID, "parent_span_id": PARENT_SPAN_ID, "turn_cost_remaining_usd": 4.25}
LANGFUSE_TRACE_ID = re.compile(r"^[0-9a-f]{32}$")
LANGFUSE_SPAN_ID = re.compile(r"^[0-9a-f]{16}$")


class FakeContext:
    def __init__(self):
        self.hooks, self.tools = {}, {}

    def register_hook(self, name, callback):
        self.hooks[name] = callback

    def register_tool(self, name, toolset, handler, description, schema):
        self.tools[name] = {"handler": handler, "schema": schema}

    def register_system_prompt_section(self, section_id, content):
        pass


@pytest.fixture(autouse=True)
def clean_state(monkeypatch, tmp_path):
    for name in ("KITCHEN_COCKPIT_URL", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    trace.reset()
    emit.reset()


def register(monkeypatch, role: str) -> dict:
    monkeypatch.setenv("KITCHEN_AGENT_ROLE", role)
    ctx = FakeContext()
    kitchen_observability.register(ctx)
    return ctx.hooks


def printed_events(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]


def test_orchestrator_starts_a_new_trace_for_every_owner_message(monkeypatch):
    hooks = register(monkeypatch, "orchestrator")
    hooks["pre_llm_call"](session_id="owner-1", user_message="Quero um prato com frango e arroz", platform="cli")
    first = trace.current("owner-1")["trace_id"]
    hooks["pre_llm_call"](session_id="owner-1", user_message="sim", platform="cli")
    second = trace.current("owner-1")["trace_id"]
    assert LANGFUSE_TRACE_ID.match(first) and LANGFUSE_TRACE_ID.match(second) and first != second


def test_a_serving_agent_adopts_the_trace_of_the_incoming_request(monkeypatch, capsys):
    hooks = register(monkeypatch, "cost_expert")
    request = {"task": "match_and_cost", "trace": INCOMING_TRACE, "owner_confirmation": None, "owner_statement": None,
               "payload": {"dish_id": 3}}
    # a contract retry appends the validation errors, which may contain braces, after the request JSON (correction C19)
    message = json.dumps(request) + "\n\nYour previous reply was invalid: {'result': 'is a required property'}"
    hooks["pre_llm_call"](session_id="expert-1", user_message=message, platform="a2a")
    assert trace.current("expert-1")["trace_id"] == TRACE_ID
    assert trace.current("expert-1")["turn_cost_remaining_usd"] == 4.25  # read by the Loop 4 cost cap

    hooks["pre_api_request"](session_id="expert-1", api_request_id="r1", api_call_count=0, model="claude-sonnet-5")
    hooks["post_api_request"](session_id="expert-1", api_request_id="r1", api_call_count=0, model="claude-sonnet-5",
                              api_duration=0.5, usage={"input_tokens": 10, "output_tokens": 5}, finish_reason="stop")
    hooks["post_llm_call"](session_id="expert-1", assistant_response="{}", platform="a2a")
    events = {event["kind"]: event for event in printed_events(capsys)}
    assert events["a2a_serve"]["trace_id"] == events["llm_call"]["trace_id"] == TRACE_ID
    assert events["a2a_serve"]["parent_span_id"] == PARENT_SPAN_ID
    assert events["llm_call"]["parent_span_id"] == events["a2a_serve"]["span_id"]


def test_mcp_tool_args_receive_the_trace_id_through_pre_tool_call_modify(monkeypatch):
    hooks = register(monkeypatch, "cost_expert")
    request = {"task": "match_and_cost", "trace": INCOMING_TRACE, "payload": {"dish_id": 3}}
    hooks["pre_llm_call"](session_id="expert-1", user_message=json.dumps(request), platform="a2a")
    directive = hooks["pre_tool_call"](tool_name="mcp__ledger__compute_dish_cost", args={"dish_id": 3}, task_id="t",
                                       session_id="expert-1", tool_call_id="c1")
    assert directive == {"action": "modify", "args": {"trace_id": TRACE_ID}}
    assert hooks["pre_tool_call"](tool_name="research", args={"task_type": "ingredient_price"}, task_id="t",
                                  session_id="expert-1", tool_call_id="c2") is None


def test_orchestrator_requests_carry_the_turn_trace_and_the_calling_span(monkeypatch, capsys):
    hooks = register(monkeypatch, "orchestrator")
    monkeypatch.setenv("KITCHEN_A2A_TOKEN", "token-orchestrator")
    a2a = FakeContext()
    kitchen_a2a.register(a2a)
    sent = {}

    def fake_send(peer_url, token, request, response_schema, timeout_s):
        sent["trace"] = request["trace"]
        return {"result": {"cmv_per_portion_display": "R$ 2,72"}, "questions_for_owner": [], "cost_usd_spent": 0.0}

    monkeypatch.setattr(validation, "call_with_contract", fake_send)
    args = {"task": "match_and_cost", "payload": {"dish_id": 3}}
    hooks["pre_llm_call"](session_id="owner-1", user_message="quanto custa o arroz com frango?", platform="cli")
    hooks["pre_tool_call"](tool_name="ask_cost_expert", args=args, task_id="t", session_id="owner-1", tool_call_id="c1")
    a2a.tools["ask_cost_expert"]["handler"](args, task_id="t", session_id="owner-1", user_task="")
    hooks["post_tool_call"](tool_name="ask_cost_expert", args=args, result="{}", task_id="t", session_id="owner-1",
                            tool_call_id="c1", duration_ms=30, status="ok")

    (call,) = [event for event in printed_events(capsys) if event["kind"] == "a2a_call" and event["status"] != "running"]
    assert sent["trace"]["trace_id"] == trace.current("owner-1")["trace_id"] == call["trace_id"]
    assert sent["trace"]["parent_span_id"] == call["span_id"] and LANGFUSE_SPAN_ID.match(call["span_id"])


def test_researcher_web_children_share_the_request_trace(monkeypatch, capsys):
    hooks = register(monkeypatch, "researcher")
    request = {"task_type": "recipe_search", "trace": INCOMING_TRACE, "items": ["frango com arroz"]}
    hooks["pre_llm_call"](session_id="researcher-1", user_message=json.dumps(request), platform="a2a")
    hooks["pre_tool_call"](tool_name="fan_out_research", args={"task_type": "recipe_search"}, session_id="researcher-1",
                           tool_call_id="f1")
    hooks["subagent_start"](parent_session_id="researcher-1", child_session_id="child-1", child_goal="Find one real recipe")
    assert hooks["transform_tool_result"](tool_name="web_extract", args={"urls": ["https://receitas.example/arroz"]},
                                          result="{}", session_id="child-1", tool_call_id="w1", duration_ms=300,
                                          status="ok") is None
    hooks["post_tool_call"](tool_name="fan_out_research", result="{}", session_id="researcher-1", tool_call_id="f1",
                            duration_ms=900, status="ok")

    events = printed_events(capsys)
    web = next(event for event in events if event["name"] == "web_extract")
    fan_out = next(event for event in events if event["name"] == "fan_out_research")
    assert web["trace_id"] == fan_out["trace_id"] == TRACE_ID
    assert web["parent_span_id"] == fan_out["span_id"]


def test_hermes_plugin_naming_and_plain_imports_share_one_trace_state(monkeypatch):
    # Hermes imports a directory plugin as hermes_plugins.<name> (hermes_cli/plugins_loader.py); kitchen_a2a and
    # kitchen_guardrails import it by its plain name, which must reach the same modules or the trace state splits.
    for name in [name for name in sys.modules if name.split(".")[0] == "kitchen_observability"]:
        monkeypatch.delitem(sys.modules, name)
    namespace = types.ModuleType("hermes_plugins")
    namespace.__path__ = []
    monkeypatch.setitem(sys.modules, "hermes_plugins", namespace)
    plugin_dir = PLUGINS / "kitchen_observability"
    spec = importlib.util.spec_from_file_location("hermes_plugins.kitchen_observability", plugin_dir / "__init__.py",
                                                  submodule_search_locations=[str(plugin_dir)])
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "hermes_plugins.kitchen_observability", module)
    spec.loader.exec_module(module)

    import kitchen_observability.trace as plain_trace
    from kitchen_observability.emit import emit as plain_emit

    assert plain_trace is sys.modules["hermes_plugins.kitchen_observability.trace"]
    assert plain_emit is sys.modules["hermes_plugins.kitchen_observability.emit"].emit
