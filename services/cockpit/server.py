"""Cockpit (PLAN.md D34, Loop 5): a live view of Dona Sálvia's pipeline, served by the Python standard library only.

POST /events (bearer token) accepts one event of contracts/events.schema.json into a ring buffer of the last 500;
GET /stream replays that buffer, then pushes each new event over Server-Sent Events; GET / is the page. A background
thread probes Langfuse's health endpoint and publishes a health event whenever its status changes. Nothing is
persisted: a restart starts empty.
"""

import hmac
import json
import os
import queue
import re
import secrets
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RING_SIZE = 500
MAX_EVENT_BYTES = 64_000
KEEPALIVE_SECONDS = 15
PROBE_INTERVAL_SECONDS = 15
HERE = Path(__file__).resolve().parent
_JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "null": type(None)}
_CHECKED_KEYWORDS = {"type", "enum", "minLength", "maxLength", "minimum", "pattern"}


def load_schema(contracts_dir: str | None = None) -> dict:
    directory = Path(contracts_dir or os.environ.get("KITCHEN_CONTRACTS_DIR") or HERE.parents[1] / "contracts")
    schema = json.loads((directory / "events.schema.json").read_text())
    unchecked = {keyword for rule in schema["properties"].values() for keyword in rule} - _CHECKED_KEYWORDS
    if unchecked or schema.get("additionalProperties") is not False:  # fail loud rather than accept unchecked events
        raise ValueError(f"events.schema.json uses keywords the cockpit does not check: {sorted(unchecked)}")
    return schema


def validation_errors(event, schema: dict) -> list[str]:
    """The few JSON Schema keywords events.schema.json uses, checked by hand: the cockpit has no dependencies (D34)."""
    if not isinstance(event, dict):
        return ["an event is a JSON object"]
    errors = [f"{key} is required" for key in schema["required"] if key not in event]
    errors += [f"{key} is not an event property" for key in event if key not in schema["properties"]]
    for key, rule in schema["properties"].items():
        if key not in event:
            continue
        value, types = event[key], rule["type"] if isinstance(rule.get("type"), list) else [rule["type"]] if "type" in rule else []
        if types and (isinstance(value, bool) or not isinstance(value, tuple(_JSON_TYPES[name] for name in types))):
            errors.append(f"{key} must be {' or '.join(types)}")
        elif "enum" in rule and value not in rule["enum"]:
            errors.append(f"{key} must be one of {rule['enum']}")
        elif isinstance(value, str) and not rule.get("minLength", 0) <= len(value) <= rule.get("maxLength", len(value)):
            errors.append(f"{key} length must be within {rule.get('minLength', 0)}..{rule.get('maxLength')}")
        elif isinstance(value, str) and "pattern" in rule and not re.search(rule["pattern"], value):
            errors.append(f"{key} must match {rule['pattern']}")
        elif isinstance(value, (int, float)) and "minimum" in rule and value < rule["minimum"]:
            errors.append(f"{key} must be at least {rule['minimum']}")
    return errors


class Hub:
    """The last events and the connected SSE clients."""

    def __init__(self, size: int = RING_SIZE):
        self.events: deque = deque(maxlen=size)
        self.clients: set[queue.Queue] = set()
        self.health: dict[str, str] = {}
        self.lock = threading.Lock()

    def publish(self, event: dict) -> None:
        with self.lock:
            self.events.append(event)
            for client in self.clients:
                client.put(event)

    def subscribe(self) -> tuple[list[dict], queue.Queue]:
        """The buffer first, marked as replay: the page fills its tables with it but does not animate the topology,
        which otherwise lights every node at once when the cockpit is opened."""
        client: queue.Queue = queue.Queue()
        with self.lock:
            self.clients.add(client)
            return [{**event, "replayed": True} for event in self.events], client

    def unsubscribe(self, client: queue.Queue) -> None:
        with self.lock:
            self.clients.discard(client)


def make_server(host: str, port: int, token: str, schema: dict | None = None) -> ThreadingHTTPServer:
    if not token:
        raise ValueError("KITCHEN_COCKPIT_TOKEN must be set: agents and kitchen-ledger authenticate their events with it")
    schema = schema or load_schema()
    hub, page = Hub(), (HERE / "index.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                self._reply(200, page, "text/html; charset=utf-8")
            elif self.path == "/health":
                self._reply(200, b'{"status": "ok"}')
            elif self.path == "/stream":
                self._stream()
            else:
                self._reply(404, b'{"error": "not found"}')

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if self.path != "/events" or length > MAX_EVENT_BYTES:
                return self._reply(404 if self.path != "/events" else 413, b'{"error": "rejected"}')
            body = self.rfile.read(length)  # read before replying, or closing with unread data resets the connection
            scheme, _, presented = self.headers.get("Authorization", "").partition(" ")
            if scheme.lower() != "bearer" or not hmac.compare_digest(presented.encode(), token.encode()):
                return self._reply(401, b'{"error": "unauthorized"}')
            try:
                event = json.loads(body)
            except ValueError:
                return self._reply(400, b'{"errors": ["the body is not JSON"]}')
            errors = validation_errors(event, schema)
            if errors:
                return self._reply(400, json.dumps({"errors": errors}).encode())
            hub.publish(event)
            self._reply(202, b'{"status": "accepted"}')

        def _reply(self, status: int, body: bytes, content_type: str = "application/json") -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _stream(self) -> None:
            replay, client = hub.subscribe()
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            try:
                for event in replay:
                    self._send_event(event)
                while True:
                    try:
                        self._send_event(client.get(timeout=KEEPALIVE_SECONDS))
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")  # also how a closed browser tab is noticed
                        self.wfile.flush()
            except OSError:
                pass
            finally:
                hub.unsubscribe(client)

        def _send_event(self, event: dict) -> None:
            self.wfile.write(b"data: " + json.dumps(event, ensure_ascii=False).encode() + b"\n\n")
            self.wfile.flush()

        def log_message(self, *args):
            pass  # one line per event would drown the container log

    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.daemon_threads = True
    httpd.hub = hub
    return httpd


def probe_langfuse(hub: Hub, base_url: str, timeout_s: float = 2.0) -> dict:
    """GET /api/public/health; publish a health event when the status differs from the previous probe."""
    started = time.monotonic()
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/api/public/health", timeout=timeout_s) as response:
            status, preview = "ok", f"HTTP {response.status}"
    except Exception as error:
        status, preview = "error", str(error)
    event = {"trace_id": "cockpit-health", "span_id": secrets.token_hex(8), "parent_span_id": None, "agent": "cockpit",
             "kind": "health", "name": "langfuse", "status": status,
             "started_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
             "duration_ms": int((time.monotonic() - started) * 1000), "model": None, "prompt_hash": None, "tokens_in": None,
             "tokens_out": None, "cost_usd": None, "preview": preview[:200]}
    if hub.health.get("langfuse") != status:  # a badge change, not a timeline row every 15 seconds
        hub.health["langfuse"] = status
        hub.publish(event)
    return event


def main() -> None:
    httpd = make_server("0.0.0.0", int(os.environ.get("COCKPIT_PORT", "8080")), os.environ.get("KITCHEN_COCKPIT_TOKEN", ""))
    langfuse_url = os.environ.get("KITCHEN_LANGFUSE_URL")
    if langfuse_url:
        def probe_forever() -> None:
            while True:
                probe_langfuse(httpd.hub, langfuse_url)
                time.sleep(PROBE_INTERVAL_SECONDS)

        threading.Thread(target=probe_forever, name="langfuse-probe", daemon=True).start()
    print(f"cockpit listening on :{httpd.server_port}", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
