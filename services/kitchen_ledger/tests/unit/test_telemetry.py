"""kitchen-ledger telemetry (PLAN.md Loop 5 step 4): an mcp_call event for every tool call and a state_snapshot after every
successful write, POSTed to the cockpit on a best-effort basis — never delaying or failing the tool."""

import http.server
import json
import logging
import threading
import time
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from kitchen_ledger import operations, server, telemetry

REPO = Path(__file__).resolve().parents[4]
VALIDATOR = Draft202012Validator(json.loads((REPO / "contracts" / "events.schema.json").read_text()))
SUMMARY = {
    "budget_initial_display": "R$ 80,00", "adjustments_total_display": "R$ 0,00", "purchases_total_display": "R$ 25,00",
    "budget_remaining_display": "R$ 55,00", "kitchen_profile": [],
    "dishes": [{"id": 1, "name": "Arroz com frango", "status": "accepted", "selected_price_display": "R$ 9,90"},
               {"id": 2, "name": "Molho de tomate", "status": "candidate", "selected_price_display": None}],
}


class FakeConn:
    """Enough of a psycopg connection for dispatch's commit/rollback and the audit insert."""

    def __init__(self):
        self.executed = []

    def execute(self, sql, params=()):
        self.executed.append(sql)

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.delenv("KITCHEN_COCKPIT_URL", raising=False)
    monkeypatch.delenv("KITCHEN_COCKPIT_TOKEN", raising=False)
    telemetry.reset()
    yield
    telemetry.flush(5)


@pytest.fixture
def sent(monkeypatch):
    events = []
    monkeypatch.setattr(telemetry, "send", events.append)
    return events


def test_events_match_the_contract_and_the_snapshot_fits_the_preview():
    call = telemetry.mcp_call_event("cost_expert", "compute_dish_cost", "0123456789abcdef0123456789abcdef",
                                    "2026-09-13T12:00:00+00:00", 42, None)
    untraced = telemetry.mcp_call_event("recipe_expert", "get_pantry", None, "2026-09-13T12:00:00+00:00", 3, "forbidden")
    snapshot = telemetry.state_snapshot_event("register_purchase", "0123456789abcdef0123456789abcdef", SUMMARY)
    many_dishes = dict(SUMMARY, dishes=[dict(SUMMARY["dishes"][0], id=index) for index in range(30)])
    long_snapshot = telemetry.state_snapshot_event("accept_dish", None, many_dishes)
    for event in (call, untraced, snapshot, long_snapshot):
        assert [error.message for error in VALIDATOR.iter_errors(event)] == [], event
    assert (call["kind"], call["name"], call["status"], call["duration_ms"]) == ("mcp_call", "compute_dish_cost", "ok", 42)
    assert untraced["status"] == "error" and "forbidden" in untraced["preview"]
    assert snapshot["preview"] == "Saldo R$ 55,00 | #1 Arroz com frango: accepted R$ 9,90 | #2 Molho de tomate: candidate"
    assert len(long_snapshot["preview"]) == 200


def test_dispatch_emits_an_mcp_call_carrying_the_trace_id(sent):
    result = server.dispatch(FakeConn(), "marketing_expert", "register_purchase", {}, trace_id="0123456789abcdef0123456789abcdef")
    assert result["error"]["code"] == "forbidden"
    (event,) = sent
    assert (event["kind"], event["name"], event["status"]) == ("mcp_call", "register_purchase", "error")
    assert event["trace_id"] == "0123456789abcdef0123456789abcdef" and "marketing_expert" in event["preview"]


def test_a_successful_write_is_followed_by_a_state_snapshot(monkeypatch, sent):
    def adjust_budget(conn, delta, evidence):
        return {"budget_remaining_display": "R$ 90,00"}

    monkeypatch.setitem(server.TOOLS, "adjust_budget", adjust_budget)
    monkeypatch.setattr(operations, "get_state_summary", lambda conn: SUMMARY)
    server.dispatch(FakeConn(), "cost_expert", "adjust_budget", {"delta": "10.00", "evidence": "pode subir 10"}, trace_id="t-1")
    assert [(event["kind"], event["trace_id"]) for event in sent] == [("mcp_call", "t-1"), ("state_snapshot", "t-1")]
    assert sent[1]["preview"].startswith("Saldo R$ 55,00")


def test_reads_and_failed_writes_take_no_snapshot(monkeypatch, sent):
    monkeypatch.setitem(server.TOOLS, "get_pantry", lambda conn: [])

    def refused(conn, delta, evidence):
        raise operations.DomainError("invalid_delta", "delta must be a non-zero amount in whole cents")

    monkeypatch.setitem(server.TOOLS, "adjust_budget", refused)
    monkeypatch.setattr(operations, "get_state_summary", lambda conn: SUMMARY)
    server.dispatch(FakeConn(), "cost_expert", "get_pantry", {})
    server.dispatch(FakeConn(), "cost_expert", "adjust_budget", {"delta": "0", "evidence": "x"})
    assert [event["kind"] for event in sent] == ["mcp_call", "mcp_call"]


def test_a_hanging_cockpit_never_delays_the_tool_and_is_logged_once(monkeypatch, caplog):
    class Slow(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            time.sleep(2.0)
            self.send_response(202)
            self.end_headers()

        def log_message(self, *args):
            pass

    cockpit = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Slow)
    cockpit.daemon_threads = True
    threading.Thread(target=cockpit.serve_forever, daemon=True).start()
    monkeypatch.setenv("KITCHEN_COCKPIT_URL", f"http://127.0.0.1:{cockpit.server_port}")
    monkeypatch.setenv("KITCHEN_COCKPIT_TOKEN", "cockpit-token")
    caplog.set_level(logging.INFO)
    try:
        started = time.monotonic()
        for index in range(3):
            telemetry.send(telemetry.mcp_call_event("cost_expert", f"tool_{index}", None, "2026-09-13T12:00:00+00:00", 1, None))
        assert time.monotonic() - started < 0.5
        telemetry.flush(10)
        assert time.monotonic() - started < 3.5  # each POST gives up after 0.5 s
    finally:
        cockpit.shutdown()
        cockpit.server_close()
    assert len([r for r in caplog.records if r.levelno >= logging.WARNING and "cockpit" in r.getMessage().lower()]) == 1


def test_without_a_cockpit_url_nothing_is_sent_or_logged(caplog):
    caplog.set_level(logging.INFO)
    telemetry.send(telemetry.mcp_call_event("cost_expert", "get_pantry", None, "2026-09-13T12:00:00+00:00", 1, None))
    telemetry.flush(1)
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def test_a_reset_announces_the_state_it_left_behind(monkeypatch, sent):
    # `make eval-reset` truncates the tables with SQL, so no write passes through the ledger and the cockpit kept
    # showing the old balance (owner: "o cockpit ainda está mostrando 71 R$"). The reset says what the state is now.
    telemetry.publish_state("eval_reset", SUMMARY)
    assert [(event["kind"], event["name"]) for event in sent] == [("state_snapshot", "eval_reset")]
    assert "Saldo" in sent[0]["preview"]
