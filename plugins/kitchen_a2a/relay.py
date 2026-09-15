"""Experts relay kitchen-ledger money results verbatim (PLAN.md correction C25, extended in Loop 3).

A live run showed the model retyping compute_dish_cost's JSON into its A2A reply and changing a margin
(62,6% became 65,1%). Money values must come from the tool, so the reply's `result` is replaced with the
latest relayed tool result of the request; the model only contributes `questions_for_owner`.
"""

import json
import os
import threading

from .costs import spent_usd
from .validation import ContractError, parse_json_object

# role -> kitchen-ledger tools whose results carry money display strings
RELAYED_TOOLS = {
    "cost_expert": {
        "mcp__ledger__compute_dish_cost", "mcp__ledger__check_budget_fit", "mcp__ledger__record_price_quote",
        "mcp__ledger__register_purchase", "mcp__ledger__adjust_budget", "mcp__ledger__correct_price",
        "mcp__ledger__select_price_scenario", "mcp__ledger__simulate_promotion", "mcp__ledger__import_pantry"},
    "marketing_expert": {"mcp__ledger__register_promotion"},
}
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
    """The kitchen-ledger JSON inside Hermes' MCP envelope {"result": "<json text>"}, possibly wrapped as untrusted data."""
    text = result if isinstance(result, str) else json.dumps(result)
    try:
        envelope = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
        inner = envelope.get("result") if isinstance(envelope, dict) else None
        payload = json.loads(inner) if isinstance(inner, str) else envelope
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def transform_tool_result(tool_name: str = "", result=None, session_id: str = "", **_) -> None:
    relayed = RELAYED_TOOLS.get(os.environ.get("KITCHEN_AGENT_ROLE", ""), set())
    if tool_name in relayed and (payload := _tool_payload(result)) is not None:
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
             "cost_usd_spent": spent_usd(session_id)}
    return json.dumps(reply, ensure_ascii=False)


def register(ctx) -> None:
    for hook in ("pre_llm_call", "transform_tool_result", "transform_llm_output"):
        ctx.register_hook(hook, globals()[hook])
