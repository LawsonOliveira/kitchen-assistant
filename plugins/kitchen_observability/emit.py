"""Observability events (PLAN.md D32, contracts/events.schema.json).

Every event is one JSON line on stdout, a POST to the cockpit and an observation in Langfuse. Telemetry protects
nobody, so unlike the guardrails it is best-effort: cockpit POSTs run on a background thread with a 0.5 s timeout,
Langfuse SDK calls only record spans in memory (its exporter ships them in the background), and each failure is
dropped and logged once until that sink works again. The owner's turn never waits for either.

Other plugins use `from kitchen_observability.emit import emit` — e.g. emit("guard_input", "input_guard",
session_id=..., status="blocked", duration_ms=..., model=..., prompt_hash=..., preview=...).
"""

import atexit
import json
import sys
import logging
import os
import queue
import threading
import time
import urllib.request
from contextlib import nullcontext
from datetime import datetime, timezone
from decimal import Decimal

from . import trace

COCKPIT_TIMEOUT_SECONDS = 0.5
COCKPIT_QUEUE_SIZE = 1000
# USD per million tokens (input, output), Anthropic first-party rates as of 2026-09. The kitchen_guardrails cost cap
# uses the same numbers (plugins/kitchen_guardrails/NOTES.md); cache reads and writes are counted as input tokens.
PRICES_USD_PER_MILLION = {"claude-sonnet-5": (Decimal("2.00"), Decimal("10.00")),
                          "claude-haiku-4-5-20251001": (Decimal("1.00"), Decimal("5.00"))}
LANGFUSE_TYPES = {"llm_call": "generation", "tool_call": "tool", "a2a_call": "tool", "mcp_call": "tool",
                  "a2a_serve": "agent", "subagent": "agent", "guard_input": "guardrail", "guard_output": "guardrail",
                  "guard_memory": "guardrail"}
log = logging.getLogger("kitchen_observability")
_queue: queue.Queue = queue.Queue(maxsize=COCKPIT_QUEUE_SIZE)
_lock = threading.Lock()
_failing: set[str] = set()
_worker: threading.Thread | None = None
_client = None
_client_built = False


def reset() -> None:
    global _client, _client_built
    with _lock:
        _failing.clear()
        _client, _client_built = None, False


def cost_usd(model, tokens_in, tokens_out) -> float | None:
    if model not in PRICES_USD_PER_MILLION or tokens_in is None or tokens_out is None:
        return None
    input_rate, output_rate = PRICES_USD_PER_MILLION[model]
    return float((Decimal(tokens_in) * input_rate + Decimal(tokens_out) * output_rate) / Decimal(1_000_000))


def start(kind: str, name: str, announce: bool = True, **fields) -> dict:
    """Open a span now: its Langfuse observation measures the real duration and its id becomes the event span_id."""
    session_id = fields.get("session_id", "")
    scope = trace.current(session_id) or {}
    trace_id = fields.get("trace_id") or scope.get("trace_id") or trace.new_trace_id()
    parent = fields["parent_span_id"] if "parent_span_id" in fields else trace.parent_span_id(session_id)
    observation = _open_observation(kind, name, trace_id, parent, scope.get("owner_session_id"), fields)
    span = {"kind": kind, "name": name, "trace_id": trace_id, "parent_span_id": parent,
            "span_id": getattr(observation, "id", None) or trace.new_span_id(), "observation": observation,
            "started_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "monotonic": time.monotonic(),
            "fields": fields}
    # The cockpit used to learn of the work only when it was over: the node lit after the fact and stayed dark while
    # the agent was busy. The span says it is running now, and the finished event closes it by span_id. A one-shot
    # event (a guard verdict, a health check) has no work in between and announces nothing.
    if announce:
        _publish(_event(span, {**fields, "status": "running"}, 0))
    return span


def finish(span: dict, **fields) -> dict:
    """Close a span: print the event, queue it for the cockpit and end its Langfuse observation."""
    fields = {**span["fields"], **fields}
    event = _event(span, fields, int((time.monotonic() - span["monotonic"]) * 1000))
    _close_observation(span["observation"], event, fields)
    _publish(event)
    return event


def emit(kind: str, name: str, **fields) -> dict:
    """One finished event: a guard verdict, a health check, or a hook whose start was never seen."""
    return finish(start(kind, name, announce=False, **fields))


def flush(timeout_s: float = 2.0) -> None:
    """Wait, at most timeout_s, for queued cockpit events (at exit and in tests)."""
    deadline = time.monotonic() + timeout_s
    while _queue.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.01)


atexit.register(flush, 1.0)


def _text(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)


def _event(span: dict, fields: dict, measured_ms: int) -> dict:
    model, tokens_in, tokens_out = fields.get("model"), fields.get("tokens_in"), fields.get("tokens_out")
    cost = fields.get("cost_usd")
    if cost is None and span["kind"] == "llm_call":
        cost = cost_usd(model, tokens_in, tokens_out)
    duration = fields.get("duration_ms")
    return {
        "trace_id": span["trace_id"], "span_id": span["span_id"], "parent_span_id": span["parent_span_id"],
        "agent": fields.get("agent") or os.environ.get("KITCHEN_AGENT_ROLE") or "unknown", "kind": span["kind"],
        "name": _text(span["name"])[:200] or "unknown", "status": fields.get("status") or "ok",
        "started_at": span["started_at"], "duration_ms": max(0, int(measured_ms if duration is None else duration)),
        "model": model, "prompt_hash": fields.get("prompt_hash"), "tokens_in": tokens_in, "tokens_out": tokens_out,
        "cost_usd": cost, "preview": _text(fields.get("preview") or "")[:200],
    }


def _failed(sink: str, error) -> None:
    with _lock:
        first = sink not in _failing
        _failing.add(sink)
    if first:
        log.warning("%s unavailable: dropping its events until it works again (%s)", sink, error)


def _worked(sink: str) -> None:
    with _lock:
        recovered = sink in _failing
        _failing.discard(sink)
    if recovered:
        log.info("%s is back: events flow again", sink)


def _langfuse():
    """The Langfuse client, built once from LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY and LANGFUSE_BASE_URL."""
    global _client, _client_built
    with _lock:
        if _client_built:
            return _client
        _client_built = True
    keys = [os.environ.get(name, "") for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_BASE_URL")]
    if not all(keys):
        log.info("Langfuse is not configured (LANGFUSE_PUBLIC_KEY/SECRET_KEY/BASE_URL): events go to stdout and the cockpit")
        return None
    try:
        from langfuse import Langfuse

        client = Langfuse(public_key=keys[0], secret_key=keys[1], base_url=keys[2], timeout=2, flush_interval=1)
    except Exception as error:
        _failed("langfuse", error)
        return None
    with _lock:
        _client = client
    return client


def _trace_attributes(owner_session_id: str | None):
    """Only orchestrator's spans carry the owner's session: spans of one trace with different session ids would overwrite it."""
    if not owner_session_id:
        return nullcontext()
    try:
        from langfuse import propagate_attributes
    except ImportError:
        return nullcontext()
    return propagate_attributes(session_id=owner_session_id, trace_name="owner turn")


def _open_observation(kind, name, trace_id, parent_span_id, owner_session_id, fields):
    client = _langfuse()
    if client is None:
        return None
    try:
        context = {"trace_id": trace_id, **({"parent_span_id": parent_span_id} if parent_span_id else {})}
        with _trace_attributes(owner_session_id):  # full content capture for the demo (D32); production would sanitize
            return client.start_observation(trace_context=context, name=_text(name)[:200] or "unknown",
                                            as_type=LANGFUSE_TYPES.get(kind, "span"), input=fields.get("input"),
                                            metadata={"agent": os.environ.get("KITCHEN_AGENT_ROLE", "unknown"), "kind": kind})
    except Exception as error:
        _failed("langfuse", error)
        return None


def _close_observation(observation, event: dict, fields: dict) -> None:
    if observation is None:
        return
    update = {"output": fields.get("output"), "status_message": event["preview"] or None,
              "level": {"error": "ERROR", "blocked": "WARNING"}.get(event["status"]),
              "metadata": {"agent": event["agent"], "status": event["status"], "duration_ms": event["duration_ms"],
                           "prompt_hash": event["prompt_hash"]}}
    if event["kind"] == "llm_call":
        update.update(model=event["model"], usage_details={"input": event["tokens_in"] or 0, "output": event["tokens_out"] or 0},
                      cost_details=None if event["cost_usd"] is None else {"total": event["cost_usd"]})
    try:
        observation.update(**{key: value for key, value in update.items() if value is not None})
        observation.end()
    except Exception as error:
        _failed("langfuse", error)
    else:
        _worked("langfuse")


def _terminal() -> bool:
    """orchestrator's classic CLI (`make chat`) owns stdout: event lines there would land on Dona Maria's screen."""
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


def _publish(event: dict) -> None:
    if not _terminal():  # container logs (`make logs | grep '"kind"'`) keep every event; the cockpit and Langfuse too
        print(json.dumps(event, ensure_ascii=False, default=str), flush=True)
    if not os.environ.get("KITCHEN_COCKPIT_URL"):
        return
    _start_worker()
    try:
        _queue.put_nowait(event)
    except queue.Full:
        _failed("cockpit", "event queue full")


def _start_worker() -> None:
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_send_forever, name="kitchen-cockpit-sender", daemon=True)
            _worker.start()


def _send_forever() -> None:
    while True:
        event = _queue.get()
        try:
            _post(event)
        except Exception as error:  # timeout, refused connection, DNS failure or a 4xx/5xx reply
            _failed("cockpit", error)
        else:
            _worked("cockpit")
        finally:
            _queue.task_done()


def _post(event: dict) -> None:
    request = urllib.request.Request(
        os.environ.get("KITCHEN_COCKPIT_URL", "").rstrip("/") + "/events", data=json.dumps(event, default=str).encode(),
        method="POST", headers={"Content-Type": "application/json",
                                "Authorization": f"Bearer {os.environ.get('KITCHEN_COCKPIT_TOKEN', '')}"})
    with urllib.request.urlopen(request, timeout=COCKPIT_TIMEOUT_SECONDS) as response:
        response.read()
