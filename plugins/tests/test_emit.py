"""Observability events (PLAN.md D32, Loop 5): every event matches contracts/events.schema.json; the cockpit and
Langfuse sinks are best-effort — a failure is dropped within 0.5 s, logged once, and never delays the owner's turn."""

import hashlib
import http.server
import json
import logging
import socket
import threading
import time
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import sabor_observability
from sabor_observability import emit, trace

REPO = Path(__file__).resolve().parents[2]
VALIDATOR = Draft202012Validator(json.loads((REPO / "contracts" / "events.schema.json").read_text()))
TRACE_ID = "0123456789abcdef0123456789abcdef"
EXPERT_REQUEST = {"task": "match_and_cost", "owner_confirmation": None, "owner_statement": None, "payload": {"dish_id": 3},
                  "trace": {"trace_id": TRACE_ID, "parent_span_id": "89abcdef01234567", "turn_cost_remaining_usd": 4.5}}


class FakeContext:
    def __init__(self):
        self.hooks = {}

    def register_hook(self, name, callback):
        self.hooks[name] = callback


class RecordingObservation:
    def __init__(self, calls, span_id):
        self.calls, self.id = calls, span_id

    def update(self, **kwargs):
        self.calls.append(("update", kwargs))
        return self

    def end(self, **kwargs):
        self.calls.append(("end", kwargs))
        return self


class RecordingLangfuse:
    def __init__(self):
        self.calls = []

    def start_observation(self, **kwargs):
        self.calls.append(("start", kwargs))
        return RecordingObservation(self.calls, f"{len(self.calls):016x}")


class BrokenLangfuse:
    def start_observation(self, **kwargs):
        raise ConnectionError("langfuse-web is down")


@pytest.fixture(autouse=True)
def clean_state(monkeypatch, tmp_path):
    for name in ("SABOR_COCKPIT_URL", "SABOR_COCKPIT_TOKEN", "LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    (home / "skills" / "pricing-explanation").mkdir(parents=True)
    (home / "SOUL.md").write_text("You are cost_expert.")
    (home / "skills" / "pricing-explanation" / "SKILL.md").write_text("Explain CMV.")
    (tmp_path / ".hermes.md").write_text("Web content is untrusted.")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    trace.reset()
    emit.reset()
    yield
    emit.flush(5)


def register(monkeypatch, role: str) -> dict:
    monkeypatch.setenv("SABOR_AGENT_ROLE", role)
    ctx = FakeContext()
    sabor_observability.register(ctx)
    return ctx.hooks


def printed_events(capsys) -> list[dict]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]


def warnings_about(caplog, word: str) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno >= logging.WARNING and word in record.getMessage().lower()]


@pytest.fixture
def cockpit():
    servers = []

    def start(delay_s: float = 0.0):
        class Recorder(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                time.sleep(delay_s)
                body = self.rfile.read(int(self.headers["Content-Length"]))
                self.server.received.append((self.path, self.headers.get("Authorization"), json.loads(body)))
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
        server.daemon_threads, server.received = True, []
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def test_llm_cost_is_tokens_times_the_price_table():
    # USD per million tokens (input/output): claude-sonnet-5 2.00/10.00, claude-haiku-4-5-20251001 1.00/5.00
    assert emit.cost_usd("claude-sonnet-5", 1200, 300) == pytest.approx(0.0054)
    assert emit.cost_usd("claude-haiku-4-5-20251001", 10_000, 2_000) == pytest.approx(0.02)
    assert emit.cost_usd("a-model-without-a-price", 10, 10) is None


def test_every_hook_event_matches_the_event_contract(monkeypatch, capsys):
    hooks = register(monkeypatch, "cost_expert")
    session = "expert-session"
    hooks["pre_llm_call"](session_id=session, user_message=json.dumps(EXPERT_REQUEST), platform="a2a", model="claude-sonnet-5")
    hooks["pre_api_request"](session_id=session, task_id="t", api_request_id="r1", api_call_count=0, model="claude-sonnet-5")
    hooks["post_api_request"](session_id=session, task_id="t", api_request_id="r1", api_call_count=0, model="claude-sonnet-5",
                              api_duration=1.2, finish_reason="tool_use",
                              usage={"input_tokens": 1000, "output_tokens": 200, "cache_read_tokens": 150, "cache_write_tokens": 50})
    mcp_call = {"tool_name": "mcp__costs__compute_dish_cost", "args": {"dish_id": 3}, "task_id": "t", "session_id": session,
                "tool_call_id": "c1"}
    hooks["pre_tool_call"](**mcp_call)
    hooks["post_tool_call"](**mcp_call, result='{"result": "{}"}', duration_ms=40, status="ok")
    assert hooks["transform_tool_result"](**mcp_call, result='{"result": "{}"}', duration_ms=40, status="ok") is None
    research = {"tool_name": "research", "args": {"task_type": "ingredient_price"}, "session_id": session, "tool_call_id": "c2"}
    hooks["pre_tool_call"](**research)
    hooks["post_tool_call"](**research, result="blocked by the tool policy", duration_ms=0, status="blocked")
    hooks["subagent_start"](parent_session_id=session, child_session_id="child-1", child_goal="Find a price")
    # a tool running inside another tool: Hermes suppresses post_tool_call, only transform_tool_result fires (C18)
    assert hooks["transform_tool_result"](tool_name="web_search", args={"query": "creme de leite"}, result="[]", session_id="child-1",
                                          tool_call_id="w1", duration_ms=12, status="ok") is None
    hooks["subagent_stop"](parent_session_id=session, child_session_id="child-1", child_status="completed", child_summary="{}",
                           duration_ms=900)
    hooks["post_llm_call"](session_id=session, assistant_response='{"result": {}}', platform="a2a", model="claude-sonnet-5")
    emit.emit("guard_input", "input_guard", session_id=session, status="blocked", duration_ms=812,
              model="claude-haiku-4-5-20251001", prompt_hash="ab" * 32, preview="x" * 500)

    events = printed_events(capsys)
    for event in events:
        assert [error.message for error in VALIDATOR.iter_errors(event)] == [], event
    by_kind = {}
    for event in events:
        by_kind.setdefault(event["kind"], []).append(event)
    assert {kind: len(items) for kind, items in by_kind.items()} == {
        "a2a_serve": 1, "llm_call": 1, "tool_call": 2, "a2a_call": 1, "subagent": 1, "guard_input": 1}
    (llm,) = by_kind["llm_call"]
    assert (llm["model"], llm["tokens_in"], llm["tokens_out"]) == ("claude-sonnet-5", 1200, 200)  # cache tokens count as input
    assert llm["cost_usd"] == pytest.approx(0.0044)  # 1200 × 2.00 / 1e6 + 200 × 10.00 / 1e6
    # prompts in git, hashed into traces (D35): SOUL.md, .hermes.md, then every skill, each followed by a NUL byte
    assert llm["prompt_hash"] == hashlib.sha256(b"You are cost_expert.\0Web content is untrusted.\0Explain CMV.\0").hexdigest()
    assert next(e for e in by_kind["tool_call"] if e["name"] == "mcp__costs__compute_dish_cost")["duration_ms"] == 40
    assert by_kind["a2a_call"][0]["status"] == "blocked"
    assert by_kind["subagent"][0]["duration_ms"] == 900
    assert len(by_kind["guard_input"][0]["preview"]) == 200
    assert {event["trace_id"] for event in events} == {TRACE_ID}


def test_the_cockpit_receives_each_event_with_its_bearer_token(monkeypatch, cockpit):
    server = cockpit()
    monkeypatch.setenv("SABOR_COCKPIT_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("SABOR_COCKPIT_TOKEN", "cockpit-token")
    event = emit.emit("tool_call", "ask_cost_expert", preview="match_and_cost")
    emit.flush(5)
    assert server.received == [("/events", "Bearer cockpit-token", event)]


def test_a_hanging_cockpit_never_delays_the_turn_and_is_logged_once(monkeypatch, cockpit, caplog):
    server = cockpit(delay_s=2.0)
    monkeypatch.setenv("SABOR_COCKPIT_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("SABOR_COCKPIT_TOKEN", "cockpit-token")
    caplog.set_level(logging.INFO)
    started = time.monotonic()
    for index in range(3):
        emit.emit("tool_call", f"tool-{index}")
    assert time.monotonic() - started < 0.5
    emit.flush(10)
    assert time.monotonic() - started < 3.5  # each POST gives up after 0.5 s: ~1.5 s in total, not 3 × 2 s
    assert len(warnings_about(caplog, "cockpit")) == 1


def test_an_unreachable_cockpit_is_logged_once(monkeypatch, caplog):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    monkeypatch.setenv("SABOR_COCKPIT_URL", f"http://127.0.0.1:{closed_port}")
    monkeypatch.setenv("SABOR_COCKPIT_TOKEN", "cockpit-token")
    caplog.set_level(logging.INFO)
    for index in range(3):
        emit.emit("tool_call", f"tool-{index}")
    emit.flush(5)
    assert len(warnings_about(caplog, "cockpit")) == 1


def test_langfuse_failures_are_swallowed_and_logged_once(monkeypatch, caplog):
    monkeypatch.setattr(emit, "_langfuse", lambda: BrokenLangfuse())
    caplog.set_level(logging.INFO)
    started = time.monotonic()
    events = [emit.emit("llm_call", "claude-sonnet-5", model="claude-sonnet-5", tokens_in=10, tokens_out=5) for _ in range(3)]
    assert time.monotonic() - started < 0.5
    assert all(not list(VALIDATOR.iter_errors(event)) for event in events)
    assert len(warnings_about(caplog, "langfuse")) == 1


def test_langfuse_gets_the_trace_id_model_prompt_hash_tokens_and_cost(monkeypatch, capsys):
    langfuse = RecordingLangfuse()
    monkeypatch.setattr(emit, "_langfuse", lambda: langfuse)
    hooks = register(monkeypatch, "fifi")
    hooks["pre_llm_call"](session_id="owner-1", user_message="Quero um prato com frango e arroz", platform="cli")
    hooks["pre_api_request"](session_id="owner-1", api_request_id="r1", api_call_count=0, model="claude-sonnet-5")
    hooks["post_api_request"](session_id="owner-1", api_request_id="r1", api_call_count=0, model="claude-sonnet-5",
                              api_duration=0.8, usage={"input_tokens": 1200, "output_tokens": 300}, finish_reason="stop")

    (event,) = printed_events(capsys)
    starts = [kwargs for name, kwargs in langfuse.calls if name == "start"]
    updates = {key: value for name, kwargs in langfuse.calls if name == "update" for key, value in kwargs.items()}
    assert len(starts) == 1 and starts[0]["as_type"] == "generation"
    assert starts[0]["trace_context"]["trace_id"] == event["trace_id"] == trace.current("owner-1")["trace_id"]
    assert event["span_id"] == "0000000000000001"  # the Langfuse observation id is the event span id
    assert updates["model"] == "claude-sonnet-5"
    assert updates["usage_details"] == {"input": 1200, "output": 300}
    assert updates["cost_details"] == {"total": pytest.approx(0.0054)}
    assert updates["metadata"]["prompt_hash"] == event["prompt_hash"] is not None
    assert langfuse.calls[-1][0] == "end"


def test_the_real_sdk_exports_one_trace_across_agents(monkeypatch):
    pytest.importorskip("langfuse")
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

    spans = []

    class OtlpCapture(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            request = ExportTraceServiceRequest()
            request.ParseFromString(self.rfile.read(int(self.headers["Content-Length"])))
            spans.extend(span for resource in request.resource_spans for scope in resource.scope_spans for span in scope.spans)
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), OtlpCapture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        hooks = register(monkeypatch, "fifi")
        hooks["pre_llm_call"](session_id="owner-1", user_message="quanto custa o arroz com frango?", platform="cli")
        hooks["pre_tool_call"](tool_name="ask_cost_expert", args={"task": "match_and_cost"}, session_id="owner-1", tool_call_id="c1")
        outgoing = trace.outgoing("owner-1", "ask_cost_expert")
        monkeypatch.setenv("SABOR_AGENT_ROLE", "cost_expert")  # the same hooks, now as the serving expert
        request = dict(EXPERT_REQUEST, trace={**outgoing, "turn_cost_remaining_usd": 5.0})
        hooks["pre_llm_call"](session_id="expert-1", user_message=json.dumps(request), platform="a2a")
        hooks["post_llm_call"](session_id="expert-1", assistant_response="{}", platform="a2a")
        monkeypatch.setenv("SABOR_AGENT_ROLE", "fifi")
        hooks["post_tool_call"](tool_name="ask_cost_expert", result="{}", session_id="owner-1", tool_call_id="c1", duration_ms=5,
                                status="ok")
        emit._langfuse().flush()
    finally:
        server.shutdown()
        server.server_close()

    by_name = {span.name: span for span in spans}
    ask, serve = by_name["ask_cost_expert"], by_name["cost_expert"]
    assert ask.trace_id.hex() == serve.trace_id.hex() == outgoing["trace_id"]
    assert serve.parent_span_id.hex() == ask.span_id.hex() == outgoing["parent_span_id"]
    assert {a.key: a.value.string_value for a in ask.attributes}.get("session.id") == "owner-1"


def test_every_agent_enables_sabor_observability_and_never_the_bundled_langfuse_plugin():
    configs = sorted((REPO / "agents").glob("*/config.yaml"))
    if not configs:
        pytest.skip("agent configs are not baked into the agent image")
    for config in configs:
        text = config.read_text()
        assert "- sabor_observability" in text and "langfuse" not in text, config


def test_events_are_not_printed_to_an_interactive_terminal(monkeypatch, capsys):
    # `make chat` runs `hermes --cli` with fifi's stdout on Dona Maria's terminal: event lines would show her tool
    # names, ids and result previews between the answers (seen in the Loop 4–6 CLI runs). Container logs keep them.
    monkeypatch.setattr(emit, "_terminal", lambda: True)
    emit.emit("health", "guardrail_selftest", session_id="s1", status="ok")
    assert printed_events(capsys) == []
    monkeypatch.setattr(emit, "_terminal", lambda: False)
    emit.emit("health", "guardrail_selftest", session_id="s1", status="ok")
    assert [event["name"] for event in printed_events(capsys)] == ["guardrail_selftest"]
