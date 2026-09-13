"""Sabor da Maria observability plugin (PLAN.md D32, Loop 5): one trace per owner turn across the five agents.

Hooks open a span when something starts (a model request, a tool call, a served A2A request, a delegated child) and
finish it when it ends; finishing prints the event, POSTs it to the cockpit and ends its Langfuse observation. Every
hook only observes — it returns None, except the trace_id added to costs-mcp tool arguments — and never raises.
"""

import functools
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

from . import emit, trace

# Hermes imports this plugin as hermes_plugins.sabor_observability (hermes_cli/plugins_loader.py); sabor_a2a and
# sabor_guardrails import it by its plain name, which must reach these same modules or the trace state splits in two.
for _suffix, _module in (("", sys.modules[__name__]), (".emit", emit), (".trace", trace)):
    sys.modules["sabor_observability" + _suffix] = _module

log = logging.getLogger("sabor_observability")
A2A_TOOLS = {"ask_recipe_expert", "ask_cost_expert", "ask_marketing_expert", "research"}
_prompt_hash: str | None = None
_broken_hooks: set[str] = set()


def prompt_hash() -> str | None:
    """sha256 of the versioned prompts this agent runs with — SOUL.md, the workspace .hermes.md, then each skill, every
    file followed by a NUL byte — so traces and eval runs compare prompts by hash (D35)."""
    home = Path(os.environ.get("HERMES_HOME", "/opt/data"))
    files = [home / "SOUL.md", Path.cwd() / ".hermes.md", *sorted((home / "skills").glob("*/SKILL.md"))]
    contents = [path.read_bytes() + b"\0" for path in files if path.is_file()]
    return hashlib.sha256(b"".join(contents)).hexdigest() if contents else None


def _role() -> str:
    return os.environ.get("SABOR_AGENT_ROLE", "unknown")


def _close(session_id: str, key: str, **fields) -> bool:
    span = trace.close_span(session_id, key)
    if span is not None:
        emit.finish(span, **fields)
    return span is not None


def pre_llm_call(session_id="", user_message="", platform="", parent_session_id="", **_):
    text = user_message if isinstance(user_message, str) else json.dumps(user_message, ensure_ascii=False, default=str)
    if platform == "subagent":
        if trace.link_child(parent_session_id, session_id) is None:
            return None  # parent unknown: the child's own events still join the latest trace
        kind = "subagent"
    elif _role() == "fifi":
        trace.start_turn(session_id)
        return None
    else:
        trace.adopt(session_id, text)
        kind = "a2a_serve"
    trace.open_span(session_id, trace.SERVE, emit.start(kind, _role(), session_id=session_id, input=text, preview=text))
    return None


def post_llm_call(session_id="", assistant_response="", **_):
    _close(session_id, trace.SERVE, preview=assistant_response, output=assistant_response)


def pre_api_request(session_id="", api_request_id="", api_call_count=0, model="", **_):
    trace.open_span(session_id, f"api:{api_request_id or api_call_count}",
                    emit.start("llm_call", model or "model", session_id=session_id, model=model or None, prompt_hash=_prompt_hash))


def post_api_request(session_id="", api_request_id="", api_call_count=0, model="", usage=None, api_duration=None,
                     finish_reason="", **_):
    usage = usage if isinstance(usage, dict) else {}
    fields = {"model": model or None, "prompt_hash": _prompt_hash, "preview": f"finish_reason: {finish_reason}",
              "tokens_in": sum(int(usage.get(key) or 0) for key in ("input_tokens", "cache_read_tokens", "cache_write_tokens")),
              "tokens_out": int(usage.get("output_tokens") or 0)}
    if not _close(session_id, f"api:{api_request_id or api_call_count}", **fields):
        emit.emit("llm_call", model or "model", session_id=session_id, duration_ms=int(float(api_duration or 0) * 1000), **fields)


def pre_tool_call(tool_name="", args=None, session_id="", tool_call_id="", **_):
    directive = trace.mcp_args(tool_name, session_id)
    kind = "a2a_call" if tool_name in A2A_TOOLS else "tool_call"
    trace.open_span(session_id, tool_call_id or tool_name, emit.start(kind, tool_name, session_id=session_id, input=args, preview=args))
    return directive


def _tool_done(tool_name="", result=None, session_id="", tool_call_id="", duration_ms=None, status="", error_message="", **_):
    key = tool_call_id or tool_name
    fields = {"status": "blocked" if status == "blocked" else "error" if status in ("error", "failed", "timeout") else "ok",
              "duration_ms": duration_ms, "preview": error_message or result, "output": result}
    if not _close(session_id, key, **fields) and not trace.was_closed(session_id, key):
        # no pre_tool_call seen for this call: report it on its own, with Hermes' measured duration
        emit.emit("a2a_call" if tool_name in A2A_TOOLS else "tool_call", tool_name or "tool", session_id=session_id, **fields)


def post_tool_call(**kwargs):
    _tool_done(**kwargs)


def transform_tool_result(**kwargs):
    # Hermes suppresses post_tool_call for tools running inside another tool (researcher's web children, C18); this
    # hook fires for every call. Returning a string would replace the result, so it always returns None.
    _tool_done(**kwargs)
    return None


def subagent_start(parent_session_id="", child_session_id="", **_):
    trace.link_child(parent_session_id or "", child_session_id or "")


def subagent_stop(child_session_id="", child_status="", child_summary="", duration_ms=None, **_):
    child = child_session_id or ""
    fields = {"status": "ok" if str(child_status).lower() in ("completed", "succeeded", "success", "ok") else "error",
              "duration_ms": duration_ms, "preview": child_summary, "output": child_summary}
    if not _close(child, trace.SERVE, **fields) and not trace.was_closed(child, trace.SERVE):
        emit.emit("subagent", f"{_role()} child", session_id=child, **fields)


HOOKS = (pre_llm_call, post_llm_call, pre_api_request, post_api_request, pre_tool_call, post_tool_call,
         transform_tool_result, subagent_start, subagent_stop)


def _observer(hook):
    """Telemetry never breaks a turn: a failing hook is logged once and returns None (result and args unchanged)."""

    @functools.wraps(hook)
    def safe(**kwargs):
        try:
            return hook(**kwargs)
        except Exception:
            if hook.__name__ not in _broken_hooks:
                _broken_hooks.add(hook.__name__)
                log.exception("sabor_observability hook %s failed; the turn continues without it", hook.__name__)
            return None

    return safe


def register(ctx) -> None:
    global _prompt_hash
    _prompt_hash = prompt_hash()
    for hook in HOOKS:
        ctx.register_hook(hook.__name__, _observer(hook))
