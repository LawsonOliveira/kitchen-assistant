"""researcher-side hooks (PLAN.md D5, correction C17): fixed task types, synchronous fan-out, URL provenance.

Hermes runs every model-issued top-level delegate_task in the background, so the A2A reply would leave before the
children finish. The researcher therefore gets one tool, fan_out_research, that launches one web child per item
through the plugin subagent lifecycle API, waits for all of them and merges the schema-valid results itself; that
merged JSON replaces whatever the model writes as its final reply.

The brief demands *real* recipes and a Haiku child can fabricate a plausible URL, so every recipe whose
source_url was not returned by web_search/web_extract in the same request is dropped and reported.
"""

import json
import re
import threading
import time

from jsonschema import Draft202012Validator

from .validation import ContractError, bundled_schema, parse_json_object

CHILD_MODEL = "claude-haiku-4-5-20251001"
CHILD_TIMEOUT_SECONDS = 90
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


def transform_tool_result(tool_name: str = "", result=None, session_id: str = "", **_) -> None:
    # Observer only (returns None, so the result is unchanged). Not post_tool_call: Hermes suppresses that hook while
    # a tool is running, and the web children run inside fan_out_research.
    if tool_name not in ("web_search", "web_extract"):
        return None
    urls = _urls(result)
    with _lock:
        _visited.setdefault(_root(session_id), set()).update(urls)
    return None


def _error(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def _child_item(lifecycle, handle, deadline: float, validator: Draft202012Validator) -> dict | None:
    """The child's schema-valid JSON object, or None when it timed out, failed or replied outside the schema."""
    if lifecycle.wait(handle, timeout_seconds=max(0.0, deadline - time.monotonic())).timed_out:
        lifecycle.cancel(handle, reason="research child timed out")
        return None
    result = lifecycle.result(handle)
    if result.terminal_state != "SUCCEEDED":
        return None
    try:
        item = parse_json_object(result.summary or "")
    except ContractError:
        return None
    return item if validator.is_valid(item) else None


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
    results = [item for handle in handles if (item := _child_item(lifecycle, handle, deadline, validator)) is not None]
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
