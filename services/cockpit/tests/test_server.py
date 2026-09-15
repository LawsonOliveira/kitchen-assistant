"""Cockpit server (PLAN.md D34, Loop 5): authenticated, contract-checked POST /events; live SSE on GET /stream with the
last 500 events replayed; the page itself; and the Langfuse health probe that feeds the status badge."""

import http.client
import http.server
import json
import socket
import threading
from pathlib import Path

import pytest

import server

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "contracts" / "tests" / "fixtures"
TOKEN = "cockpit-test-token"
VALID_EVENT = json.loads((FIXTURES / "valid" / "events__tool_call.json").read_text())


@pytest.fixture
def cockpit():
    httpd = server.make_server("127.0.0.1", 0, TOKEN)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


def post(httpd, body, token: str | None = TOKEN) -> int:
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})}
    connection.request("POST", "/events", body=body if isinstance(body, bytes) else json.dumps(body), headers=headers)
    status = connection.getresponse().status
    connection.close()
    return status


def open_stream(httpd):
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
    connection.request("GET", "/stream")
    response = connection.getresponse()
    assert response.status == 200 and response.getheader("Content-Type").startswith("text/event-stream")
    return connection, response


def read_events(response, count: int) -> list[dict]:
    events = []
    while len(events) < count:
        line = response.fp.readline().decode()
        assert line, "stream closed"
        if line.startswith("data:"):
            events.append(json.loads(line[len("data:"):]))
    return events


def test_post_without_the_right_token_is_401(cockpit):
    assert post(cockpit, VALID_EVENT, token=None) == 401
    assert post(cockpit, VALID_EVENT, token="wrong-token") == 401


@pytest.mark.parametrize("path", sorted((FIXTURES / "invalid").glob("events__*.json")), ids=lambda p: p.name)
def test_an_event_outside_the_contract_is_400(cockpit, path):
    assert post(cockpit, json.loads(path.read_text())) == 400


def test_valid_events_are_accepted_and_garbage_is_400(cockpit):
    for path in sorted((FIXTURES / "valid").glob("events__*.json")):
        assert post(cockpit, json.loads(path.read_text())) == 202, path.name
    assert post(cockpit, b"not json") == 400


def test_a_posted_event_is_delivered_over_sse(cockpit):
    connection, response = open_stream(cockpit)
    try:
        assert post(cockpit, VALID_EVENT) == 202
        assert read_events(response, 1) == [VALID_EVENT]
    finally:
        connection.close()


def test_the_ring_buffer_keeps_the_last_500_events(cockpit):
    for index in range(505):
        assert post(cockpit, dict(VALID_EVENT, name=f"event-{index}")) == 202
    connection, response = open_stream(cockpit)
    try:
        replayed = read_events(response, 500)
    finally:
        connection.close()
    assert [event["name"] for event in replayed] == [f"event-{index}" for index in range(5, 505)]
    # Opening the cockpit lit every node at once: the page animates what it receives, and the replay looks live.
    assert all(event["replayed"] is True for event in replayed)


def test_the_page_has_the_pipeline_nodes_and_listens_to_the_stream(cockpit):
    connection = http.client.HTTPConnection("127.0.0.1", cockpit.server_port, timeout=5)
    connection.request("GET", "/")
    response = connection.getresponse()
    page = response.read().decode()
    connection.close()
    assert response.status == 200 and "EventSource" in page
    for node in ("guard_input", "orchestrator", "recipe_expert", "cost_expert", "marketing_expert", "researcher", "mcp", "guard_output"):
        assert f'data-node="{node}"' in page


def test_the_langfuse_probe_publishes_a_health_event(cockpit):
    class Health(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"status": "OK"}' if self.path == "/api/public/health" else b"{}"
            self.send_response(200 if self.path == "/api/public/health" else 404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    langfuse = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Health)
    threading.Thread(target=langfuse.serve_forever, daemon=True).start()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        closed_port = probe.getsockname()[1]
    try:
        up = server.probe_langfuse(cockpit.hub, f"http://127.0.0.1:{langfuse.server_port}")
        down = server.probe_langfuse(cockpit.hub, f"http://127.0.0.1:{closed_port}")
    finally:
        langfuse.shutdown()
        langfuse.server_close()
    schema = server.load_schema()
    for event in (up, down):
        assert server.validation_errors(event, schema) == [] and (event["kind"], event["name"]) == ("health", "langfuse")
    assert (up["status"], down["status"]) == ("ok", "error")
    connection, response = open_stream(cockpit)
    try:
        assert [event["status"] for event in read_events(response, 2)] == ["ok", "error"]
    finally:
        connection.close()
