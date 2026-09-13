"""researcher-side hooks (PLAN.md D5, correction C17): fixed task types, synchronous fan-out, URL provenance.

Hermes runs every model-issued top-level delegate_task in the background, so the A2A reply would leave before the
children finish. The researcher therefore gets one tool, fan_out_research, that launches one web child per item
through the plugin subagent lifecycle API, waits for all of them and merges the schema-valid results itself; that
merged JSON replaces whatever the model writes as its final reply.

The brief demands *real* recipes and a Haiku child can fabricate a plausible URL, so every recipe whose
source_url was not returned by web_search/web_extract in the same request is dropped and reported.
"""

import json
import logging
import os
import re
import threading
import time
from pathlib import Path

from jsonschema import Draft202012Validator

from . import web_replay
from .validation import ContractError, bundled_schema, parse_json_object

CHILD_MODEL = "claude-haiku-4-5-20251001"
CHILD_TIMEOUT_SECONDS = 90
REPAIR_TIMEOUT_SECONDS = 45
REPAIR_GOAL = ("Fix a research reply that does not match its JSON Schema. Change only what the errors name; when a "
               "value is unknown, read its source_url again with web_extract and never guess. Reply with only the "
               "corrected JSON object.")
# task_type -> (contract file, JSON pointer of one result item)
ITEM_SCHEMAS = {
    "recipe_search": ("recipe.schema.json", ""),
    "ingredient_price": ("research/ingredient_price.response.json", "/properties/results/items"),
    "menu_reference": ("research/menu_reference.response.json", "/properties/results/items"),
}
CHILD_GOALS = {
    "recipe_search": "Find one real recipe page written in Brazilian Portuguese for: {item}. Use web_search, read the best result with "
                     "web_extract, and reply with only the JSON object of that recipe.",
    "ingredient_price": "Find the current retail price in Brazil, in reais, of: {item}, on a real Brazilian "
                        "supermarket page. Use web_search and web_extract, and reply with only the JSON object.",
    "menu_reference": "Find how delivery restaurants on iFood name and describe: {item}. Use web_search and "
                      "web_extract, and reply with only the JSON object.",
}
TOOL_DESCRIPTION = ("Research every item of the request in parallel (one web child per item) and return the merged, "
                    "schema-checked JSON reply. Call it exactly once per request.")
TOOL_PARAMETERS = {
    "type": "object", "required": ["task_type", "items"],
    "properties": {"task_type": {"type": "string", "enum": sorted(ITEM_SCHEMAS)},
                   "items": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5}},
}
log = logging.getLogger(__name__)
_URL = re.compile(r"https?://[^\s\"'<>\]\\]+")  # parentheses allowed: real recipe URLs contain them
_lock = threading.Lock()
_request_type: dict[str, str] = {}
_parent: dict[str, str] = {}
_visited: dict[str, set[str]] = {}
_merged: dict[str, dict] = {}


def reset() -> None:
    with _lock:
        _request_type.clear(), _parent.clear(), _visited.clear(), _merged.clear()


def _root(session_id: str) -> str:
    while session_id in _parent:
        session_id = _parent[session_id]
    return session_id


def _first_json_object(text: str) -> dict:
    # A contract retry appends validation errors (which may contain braces) after the request JSON.
    return json.JSONDecoder().raw_decode(text[text.index("{"):])[0]


def remember_request(session_id: str, user_message: str) -> None:
    try:
        task_type = _first_json_object(user_message).get("task_type", "")
    except (ValueError, AttributeError):
        task_type = ""
    with _lock:
        _request_type[session_id] = task_type
        # a reused A2A session must not reuse URLs visited or results merged for an earlier request
        _visited.pop(session_id, None), _merged.pop(session_id, None)


def pre_llm_call(session_id: str = "", user_message: str = "", platform: str = "", **_):
    if platform != "subagent":
        remember_request(session_id, user_message or "")
    return None


def pre_tool_call(tool_name: str = "", **_):
    if tool_name == "delegate_task":
        return {"action": "block", "message": "use fan_out_research: a background delegation cannot answer this request"}
    return None


def subagent_start(parent_session_id: str = "", child_session_id: str = "", **_) -> None:
    if parent_session_id and child_session_id:
        with _lock:
            _parent[child_session_id] = parent_session_id


def _urls(value) -> set[str]:
    """Every URL in a web tool result; JSON is decoded first so escaped slashes and punctuation stay exact."""
    if isinstance(value, dict):
        return set().union(*map(_urls, value.values()))
    if isinstance(value, list):
        return set().union(*map(_urls, value))
    if not isinstance(value, str):
        return set()
    try:
        decoded = json.loads(value)
    except ValueError:
        return {url.rstrip(".,;") for url in _URL.findall(value)}
    return _urls(decoded) if isinstance(decoded, (dict, list)) else {url.rstrip(".,;") for url in _URL.findall(value)}


def _fetched_urls(tool_name: str, result) -> set[str]:
    """Every URL web_search returned, but only the pages web_extract really fetched: Hermes answers a blocked or
    failed URL with an entry {"url", "content": "", "error"} that still carries the URL."""
    if tool_name == "web_search":
        return _urls(result)
    try:
        data = json.loads(result) if isinstance(result, str) else result
    except ValueError:
        return set()
    entries = data.get("results") if isinstance(data, dict) else None
    return {entry["url"] for entry in entries if isinstance(entry, dict) and isinstance(entry.get("url"), str)
            and entry.get("content") and not entry.get("error")} if isinstance(entries, list) else set()


def transform_tool_result(tool_name: str = "", args: dict | None = None, result=None, session_id: str = "", **_):
    # Not post_tool_call: Hermes suppresses that hook while a tool is running, and the web children run inside
    # fan_out_research (C18). Returns None (result unchanged) except in the eval profile, which replays fixture
    # pages (C27).
    if tool_name not in ("web_search", "web_extract"):
        return None
    fixtures_dir = os.environ.get("SABOR_WEB_FIXTURES_DIR")
    replayed = web_replay.replay(Path(fixtures_dir), tool_name, args) if fixtures_dir else None
    urls = _fetched_urls(tool_name, replayed if replayed is not None else result)
    with _lock:
        _visited.setdefault(_root(session_id), set()).update(urls)
    return replayed


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def _child_reply(lifecycle, handle, deadline: float, validator: Draft202012Validator) -> tuple[dict | None, dict | None, str]:
    """(schema-valid item, schema-invalid JSON object worth one repair, reason it is not valid) for one child."""
    if lifecycle.wait(handle, timeout_seconds=max(0.0, deadline - time.monotonic())).timed_out:
        lifecycle.cancel(handle, reason="research child timed out")
        return None, None, "timed out"
    result = lifecycle.result(handle)
    if result.terminal_state != "SUCCEEDED":
        return None, None, f"child {getattr(result.terminal_state, 'value', result.terminal_state)}"
    try:
        item = parse_json_object(result.summary or "")
    except ContractError:
        return None, None, "reply is not a JSON object"  # nothing to repair: a repair would invent the data
    errors = [f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}" for error in validator.iter_errors(item)]
    return (None, item, "; ".join(errors[:5])) if errors else (item, None, "")


def fan_out(lifecycle, request_cls, session_id: str, task_type: str, items: list[str]) -> dict:
    if task_type not in ITEM_SCHEMAS or _request_type.get(session_id) != task_type:
        return _error("unknown_task_type", f"task_type must be the request's task_type, one of {sorted(ITEM_SCHEMAS)}")
    if session_id in _merged:
        return _error("already_called", "fan_out_research runs once per request; reply with its previous result")
    schema = bundled_schema(*ITEM_SCHEMAS[task_type])
    context = "Your reply must be only one JSON object matching this JSON Schema:\n" + json.dumps(schema, ensure_ascii=False)
    handles = [lifecycle.launch(request_cls(goal=CHILD_GOALS[task_type].format(item=item), context=context,
                                            model=CHILD_MODEL, allowed_toolsets=("web",))) for item in items[:5]]
    deadline, validator = time.monotonic() + CHILD_TIMEOUT_SECONDS, Draft202012Validator(schema)
    replies = [_child_reply(lifecycle, handle, deadline, validator) for handle in handles]
    # Same rule as call_with_contract: a reply outside the contract gets exactly one retry with its errors.
    repairs = {index: lifecycle.launch(request_cls(
        goal=REPAIR_GOAL, model=CHILD_MODEL, allowed_toolsets=("web",),
        context=f"{context}\n\nReply to fix:\n{json.dumps(invalid, ensure_ascii=False)}\n\nErrors: {reason}"))
        for index, (_, invalid, reason) in enumerate(replies) if invalid is not None}
    repair_deadline = time.monotonic() + REPAIR_TIMEOUT_SECONDS
    for index, handle in repairs.items():
        item, _, reason = _child_reply(lifecycle, handle, repair_deadline, validator)
        replies[index] = (item, None, f"after one repair: {reason}")
    results = []
    for item, _, reason in replies:
        if item is None:
            log.warning("research child dropped (%s): %s", task_type, reason)
        else:
            results.append(item)
    merged = {"task_type": task_type, "results": results}
    if task_type == "recipe_search":
        visited = _visited.get(_root(session_id), set())
        merged["results"] = [recipe for recipe in results if recipe["source_url"] in visited]
        merged["unverified_source"] = [recipe["source_url"] for recipe in results if recipe["source_url"] not in visited]
    merged["cost_usd_spent"] = 0.0  # TODO(Loop 4 step 6c): the measured spend of this request
    with _lock:
        _merged[session_id] = merged
    return merged


def transform_llm_output(response_text: str = "", session_id: str = "", platform: str = "", **_):
    if platform == "subagent" or session_id not in _merged:
        return None  # no fan-out result: the caller's contract validation fails loud and retries once
    return json.dumps(_merged[session_id], ensure_ascii=False)


def register(ctx) -> None:
    from agent.subagent_lifecycle import SubagentLaunchRequest

    def fan_out_research(args: dict, session_id: str = "", **_) -> str:
        reply = fan_out(ctx.subagent_lifecycle, SubagentLaunchRequest, session_id, args.get("task_type"),
                        list(args.get("items") or []))
        return json.dumps(reply, ensure_ascii=False)

    ctx.register_tool(name="fan_out_research", toolset="sabor_a2a", handler=fan_out_research, description=TOOL_DESCRIPTION,
                      schema={"name": "fan_out_research", "description": TOOL_DESCRIPTION, "parameters": TOOL_PARAMETERS})
    for hook in ("pre_llm_call", "pre_tool_call", "transform_tool_result", "subagent_start", "transform_llm_output"):
        ctx.register_hook(hook, globals()[hook])
