"""Trace context of one owner turn across the five agents (PLAN.md D32, Loop 5).

fifi starts a trace for every owner message; sabor_a2a puts {trace_id, parent_span_id} in every A2A request; the
serving agent adopts it from the request JSON and its delegated web children inherit it; costs-mcp tool calls get
the trace_id in their arguments, so audit_log rows belong to the same trace.

State is keyed by Hermes session id rather than a ContextVar: every hook and tool handler receives session_id, while
the hooks, tool handlers and children of one turn run on different threads.
"""

import json
import secrets
import threading
from collections import OrderedDict, deque

MAX_SESSIONS = 1000  # every A2A request is a new session: bound the memory of a long-running gateway
SERVE = "@serve"  # key of the span covering a served A2A request or a delegated child's whole run
_lock = threading.RLock()
_sessions: "OrderedDict[str, dict]" = OrderedDict()
_latest: dict | None = None


def new_trace_id() -> str:
    return secrets.token_hex(16)  # Langfuse trace ids are 32 lowercase hex characters


def new_span_id() -> str:
    return secrets.token_hex(8)  # OpenTelemetry span ids are 16 lowercase hex characters


def reset() -> None:
    global _latest
    with _lock:
        _sessions.clear()
        _latest = None


def _new_scope(session_id: str, trace_id: str, parent_span_id: str | None, remaining=None, owner_session_id=None) -> dict:
    global _latest
    scope = {"trace_id": trace_id, "parent_span_id": parent_span_id, "turn_cost_remaining_usd": remaining,
             "owner_session_id": owner_session_id, "open": OrderedDict(), "closed": deque(maxlen=200)}
    with _lock:
        _sessions[session_id] = scope
        _sessions.move_to_end(session_id)
        while len(_sessions) > MAX_SESSIONS:
            _sessions.popitem(last=False)
        _latest = scope
    return scope


def start_turn(session_id: str) -> dict:
    """fifi: a new trace for every owner message; the owner's session groups her turns in Langfuse."""
    return _new_scope(session_id, new_trace_id(), None, owner_session_id=session_id or None)


def _incoming_trace(text: str) -> dict | None:
    try:  # the request is the first JSON object: a contract retry appends validation errors after it (C19)
        request = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
    except ValueError:
        return None
    incoming = request.get("trace") if isinstance(request, dict) else None
    valid = isinstance(incoming, dict) and isinstance(incoming.get("trace_id"), str) and incoming["trace_id"]
    return incoming if valid else None


def adopt(session_id: str, user_message: str) -> dict:
    """A serving agent joins its caller's trace; a request without one still gets a trace (telemetry refuses nothing)."""
    incoming = _incoming_trace(user_message or "")
    if incoming is None:
        return _new_scope(session_id, new_trace_id(), None)
    parent, remaining = incoming.get("parent_span_id"), incoming.get("turn_cost_remaining_usd")
    return _new_scope(session_id, incoming["trace_id"], parent if isinstance(parent, str) else None,
                      remaining if isinstance(remaining, (int, float)) and not isinstance(remaining, bool) else None)


def link_child(parent_session_id: str, child_session_id: str) -> dict | None:
    """A delegated child joins its parent's trace, under the innermost open span (the tool that launched it)."""
    with _lock:
        if child_session_id in _sessions:
            return _sessions[child_session_id]
        parent = _sessions.get(parent_session_id)
        if parent is None or not child_session_id:
            return None
        spans = list(parent["open"].values())
        return _new_scope(child_session_id, parent["trace_id"], spans[-1]["span_id"] if spans else parent["parent_span_id"],
                          parent["turn_cost_remaining_usd"], parent["owner_session_id"])


def current(session_id: str = "") -> dict | None:
    """The session's trace scope (trace_id, parent_span_id, turn_cost_remaining_usd received from the caller), else the
    latest one of this process — e.g. a guard event without a session id. Read-only for callers."""
    with _lock:
        return _sessions.get(session_id) or _latest


def parent_span_id(session_id: str) -> str | None:
    """Parent of a new span in this session: the served request or child run, else what the caller sent."""
    scope = current(session_id)
    if scope is None:
        return None
    serve = scope["open"].get(SERVE)
    return serve["span_id"] if serve else scope["parent_span_id"]


def outgoing(session_id: str, tool_name: str) -> dict:
    """{trace_id, parent_span_id} for an A2A request: this turn's trace, under the span of the tool call sending it."""
    scope = current(session_id)
    if scope is None:
        return {"trace_id": new_trace_id(), "parent_span_id": None}
    with _lock:
        calling = [span for span in scope["open"].values() if span["name"] == tool_name]
    return {"trace_id": scope["trace_id"], "parent_span_id": calling[-1]["span_id"] if calling else parent_span_id(session_id)}


def mcp_args(tool_name: str, session_id: str) -> dict | None:
    """pre_tool_call directive adding the trace_id to costs-mcp tool arguments (it lands in audit_log)."""
    scope = current(session_id)
    if not tool_name.startswith("mcp__costs__") or scope is None:
        return None
    return {"action": "modify", "args": {"trace_id": scope["trace_id"]}}


def open_span(session_id: str, key: str, span: dict) -> None:
    with _lock:
        scope = _sessions.get(session_id)
        if scope is None:  # a hook for a session never seen (no pre_llm_call): keep it in the latest trace
            latest = _latest
            scope = _new_scope(session_id, latest["trace_id"], latest["parent_span_id"], latest["turn_cost_remaining_usd"],
                               latest["owner_session_id"]) if latest else _new_scope(session_id, span["trace_id"], None)
        scope["open"][key] = span


def close_span(session_id: str, key: str) -> dict | None:
    with _lock:
        scope = _sessions.get(session_id)
        span = scope["open"].pop(key, None) if scope else None
        if span is not None:
            scope["closed"].append(key)
    return span


def was_closed(session_id: str, key: str) -> bool:
    """post_tool_call and transform_tool_result both report a top-level tool call: only the first one counts."""
    with _lock:
        scope = _sessions.get(session_id)
        return scope is not None and key in scope["closed"]
