"""Observability plugin — Loop 0 stub: tool calls become JSON lines on stdout (see emit.py)."""

from .emit import emit


def _pre_tool_call(tool_name: str = "", task_id: str = "", session_id: str = "", **_):
    emit("tool_call", tool_name or "unknown", status="started", task_id=task_id, session_id=session_id)
    return None  # observe only: never block or modify


def _post_tool_call(tool_name: str = "", status: str = "", duration_ms=None, error_type: str = "",
                    task_id: str = "", session_id: str = "", **_):
    emit("tool_call", tool_name or "unknown", status=status or "ok", duration_ms=duration_ms,
         error_type=error_type, task_id=task_id, session_id=session_id)


def register(ctx) -> None:
    ctx.register_hook("pre_tool_call", _pre_tool_call)
    ctx.register_hook("post_tool_call", _post_tool_call)
