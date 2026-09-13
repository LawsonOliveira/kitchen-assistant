"""sabor_a2a.client against a fake A2A v1.0 JSON-RPC peer (the shape Hermes' a2a plugin serves)."""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sabor_a2a.client import A2AAuthError, A2AError, A2ATimeout, send_message

GOOD_TOKEN = "caller-token"


class FakePeer(BaseHTTPRequestHandler):
    received = []

    def log_message(self, *args):
        pass

    def _reply(self, status, body):
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakePeer.received.append({"headers": dict(self.headers), "body": body})
        if self.headers.get("Authorization") != f"Bearer {GOOD_TOKEN}":
            return self._reply(401, {"jsonrpc": "2.0", "id": body.get("id"), "error": {"code": -32001, "message": "unauthorized"}})
        text = body["params"]["message"]["parts"][0]["text"]
        if text == "slow":
            time.sleep(2)
        if text == "rpc-error":
            return self._reply(200, {"jsonrpc": "2.0", "id": body["id"], "error": {"code": -32603, "message": "boom"}})
        task = {
            "id": "task-1",
            "contextId": body["params"]["message"]["contextId"],
            "status": {"state": "TASK_STATE_COMPLETED"},
            "artifacts": [{"parts": [{"text": f"echo: {text}", "mediaType": "text/plain"}]}],
        }
        self._reply(200, {"jsonrpc": "2.0", "id": body["id"], "result": {"task": task}})


@pytest.fixture
def peer_url():
    FakePeer.received.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakePeer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_round_trip_returns_artifact_text(peer_url):
    assert send_message(peer_url, GOOD_TOKEN, "oi", timeout_s=5) == "echo: oi"
    request = FakePeer.received[0]
    assert request["body"]["method"] == "SendMessage"
    assert request["headers"]["A2A-Version"] == "1.0"
    assert request["body"]["params"]["message"]["role"] == "ROLE_USER"


def test_each_call_uses_a_new_context_id(peer_url):
    send_message(peer_url, GOOD_TOKEN, "um", timeout_s=5)
    send_message(peer_url, GOOD_TOKEN, "dois", timeout_s=5)
    first, second = (r["body"]["params"]["message"]["contextId"] for r in FakePeer.received)
    assert first and second and first != second


def test_bad_token_raises_auth_error(peer_url):
    with pytest.raises(A2AAuthError):
        send_message(peer_url, "wrong", "oi", timeout_s=5)


def test_timeout_raises(peer_url):
    with pytest.raises(A2ATimeout):
        send_message(peer_url, GOOD_TOKEN, "slow", timeout_s=0.5)


def test_jsonrpc_error_fails_loud(peer_url):
    with pytest.raises(A2AError, match="boom"):
        send_message(peer_url, GOOD_TOKEN, "rpc-error", timeout_s=5)
