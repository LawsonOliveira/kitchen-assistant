"""cost_expert relays costs-mcp results verbatim (PLAN.md correction C25).

A live run showed the model retyping compute_dish_cost's JSON into its A2A reply and changing a margin
(62,6% became 65,1%). Money values must come from the tool, so the reply's `result` is replaced with the
latest relayed tool result of the request; the model only contributes `questions_for_owner`.
"""

import json
import threading

from .validation import ContractError, parse_json_object

RELAYED_TOOLS = {"mcp__costs__compute_dish_cost"}
_lock = threading.Lock()
_latest: dict[str, dict] = {}


def reset() -> None:
    with _lock:
        _latest.clear()


def pre_llm_call(session_id: str = "", platform: str = "", **_):
    if platform != "subagent":
        with _lock:
            _latest.pop(session_id, None)  # a reused A2A session must not relay an earlier request's result
    return None


def _tool_payload(result) -> dict | None:
    """The costs-mcp JSON inside Hermes' MCP envelope {"result": "<json text>"}, possibly wrapped as untrusted data."""
    text = result if isinstance(result, str) else json.dumps(result)
    try:
        envelope = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
        inner = envelope.get("result") if isinstance(envelope, dict) else None
        payload = json.loads(inner) if isinstance(inner, str) else envelope
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def transform_tool_result(tool_name: str = "", result=None, session_id: str = "", **_) -> None:
    if tool_name in RELAYED_TOOLS and (payload := _tool_payload(result)) is not None:
        with _lock:
            _latest[session_id] = payload
    return None  # observer only: the model sees the result unchanged


def transform_llm_output(response_text: str = "", session_id: str = "", platform: str = "", **_):
    if platform == "subagent" or session_id not in _latest:
        return None
    try:
        questions = parse_json_object(response_text).get("questions_for_owner")
    except ContractError:
        questions = None
    reply = {"result": _latest[session_id], "questions_for_owner": questions if isinstance(questions, list) else [],
             "cost_usd_spent": 0.0}  # TODO(Loop 4 step 6c): the measured spend of this request
    return json.dumps(reply, ensure_ascii=False)


def register(ctx) -> None:
    for hook in ("pre_llm_call", "transform_tool_result", "transform_llm_output"):
        ctx.register_hook(hook, globals()[hook])
