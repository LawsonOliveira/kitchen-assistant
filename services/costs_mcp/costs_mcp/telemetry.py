"""costs-mcp telemetry (PLAN.md Loop 5 step 4): an mcp_call event for every tool call and a state_snapshot after every
successful write, POSTed to the cockpit.

Best-effort, like the agents' sabor_observability.emit: a background thread, a 0.5 s timeout, failures dropped and
logged once. A tool result never waits for telemetry and never fails because of it. (A small copy of the agents'
sender instead of a shared package: costs-mcp and the agents are separate images with separate dependencies.)
"""

import json
import logging
import os
import queue
import secrets
import threading
import time
import urllib.request
from datetime import datetime, timezone

from costs_mcp import operations

COCKPIT_TIMEOUT_SECONDS = 0.5
# Tools that never change state: no snapshot after them.
READ_ONLY_TOOLS = {"get_pantry", "get_state_summary", "check_pantry_match", "get_launch_menu", "check_viability",
                   "compute_dish_cost", "check_budget_fit", "simulate_promotion"}
log = logging.getLogger("costs_mcp.telemetry")
_queue: queue.Queue = queue.Queue(maxsize=1000)
_lock = threading.Lock()
_state = {"failing": False, "worker": None}


def reset() -> None:
    _state["failing"] = False


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _event(kind: str, name: str, trace_id: str | None, started_at: str, duration_ms: float, status: str, preview: str) -> dict:
    return {"trace_id": trace_id or "untraced", "span_id": secrets.token_hex(8), "parent_span_id": None, "agent": "costs_mcp",
            "kind": kind, "name": name, "status": status, "started_at": started_at, "duration_ms": max(0, int(duration_ms)),
            "model": None, "prompt_hash": None, "tokens_in": None, "tokens_out": None, "cost_usd": None, "preview": preview[:200]}


def mcp_call_event(agent: str, tool: str, trace_id: str | None, started_at: str, duration_ms: float, error_code: str | None) -> dict:
    return _event("mcp_call", tool, trace_id, started_at, duration_ms, "error" if error_code else "ok", f"{agent}: {error_code or 'ok'}")


def state_snapshot_event(tool: str, trace_id: str | None, summary: dict) -> dict:
    """The cockpit's state panel: budget left and every dish, as one line ("Saldo R$ 55,00 | #1 Arroz com frango: accepted R$ 9,90")."""
    dishes = [" ".join(filter(None, (f"#{dish['id']} {dish['name']}: {dish['status']}", dish.get("selected_price_display"))))
              for dish in summary["dishes"]]
    return _event("state_snapshot", tool, trace_id, now(), 0, "ok", " | ".join([f"Saldo {summary['budget_remaining_display']}", *dishes]))


def after_call(conn, agent: str, tool: str, trace_id: str | None, started_at: str, started_monotonic: float,
               error_code: str | None) -> None:
    """Called by server.dispatch once the audit row is committed."""
    try:
        send(mcp_call_event(agent, tool, trace_id, started_at, (time.monotonic() - started_monotonic) * 1000, error_code))
        if error_code is None and tool not in READ_ONLY_TOOLS:
            send(state_snapshot_event(tool, trace_id, operations.get_state_summary(conn)))
    except Exception as error:  # the tool already succeeded or failed on its own; telemetry must not change that
        log.warning("telemetry skipped for %s: %s", tool, error)


def send(event: dict) -> None:
    print(json.dumps(event, ensure_ascii=False), flush=True)
    if not os.environ.get("SABOR_COCKPIT_URL"):
        return
    with _lock:
        if _state["worker"] is None or not _state["worker"].is_alive():
            _state["worker"] = threading.Thread(target=_send_forever, name="cockpit-sender", daemon=True)
            _state["worker"].start()
    try:
        _queue.put_nowait(event)
    except queue.Full:
        _failed("event queue full")


def flush(timeout_s: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_s
    while _queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.01)


def _failed(error) -> None:
    with _lock:
        first, _state["failing"] = not _state["failing"], True
    if first:
        log.warning("cockpit unavailable: dropping events until it works again (%s)", error)


def _send_forever() -> None:
    while True:
        event = _queue.get()
        try:
            request = urllib.request.Request(
                os.environ.get("SABOR_COCKPIT_URL", "").rstrip("/") + "/events", data=json.dumps(event).encode(), method="POST",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {os.environ.get('SABOR_COCKPIT_TOKEN', '')}"})
            with urllib.request.urlopen(request, timeout=COCKPIT_TIMEOUT_SECONDS) as response:
                response.read()
        except Exception as error:  # timeout, refused connection, DNS failure or a 4xx/5xx reply
            _failed(error)
        else:
            _state["failing"] = False
        finally:
            _queue.task_done()
