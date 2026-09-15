"""Deterministic fast path for cost_expert (PLAN.md PL9, lever 1).

A task that is one kitchen-ledger call (match_and_cost: two reads) is answered without a model loop: the reply carries the
tool's result, exactly what the relay would put there. Tasks that need judgment or research, a click-required task
without its click, and any tool error go to the model as before; an error means nothing was written.
"""

import json
import logging

log = logging.getLogger(__name__)
CLICK_REQUIRED = {"register_purchase", "adjust_budget", "select_price_scenario", "import_pantry_apply", "accept", "confirm_measure"}


def _evidence(request: dict) -> str:
    return (request.get("owner_confirmation") or {}).get("summary") or request.get("owner_statement") or ""


def _calls(request: dict) -> list[tuple[str, dict]] | None:
    task, p = request.get("task"), request.get("payload") or {}
    if task in CLICK_REQUIRED and not request.get("owner_confirmation"):
        return None
    tool = {
        "budget_fit": lambda: [("check_budget_fit", {"dish_id": p["dish_id"]})],
        "match_and_cost": lambda: [("check_pantry_match", {"dish_id": p["dish_id"]}), ("compute_dish_cost", {"dish_id": p["dish_id"]})],
        "select_price_scenario": lambda: [("select_price_scenario", {"dish_id": p["dish_id"], "target_cmv_pct": p["target_cmv_pct"]})],
        "simulate_promotion": lambda: [("simulate_promotion", {"dish_id": p["dish_id"], "discount_pct": p["discount_pct"]})],
        "correct_price": lambda: [("correct_price", {"ingredient_name": p["ingredient"], "total_price_paid": p["total_price_paid"],
                                                     "quantity": p["quantity"], "unit": p["unit"], "evidence": _evidence(request)})],
        "confirm_price_quote": lambda: [("record_price_quote", {
            "ingredient_name": p["ingredient"], "kind": "food", "package_quantity": p["package_quantity"], "package_unit": p["package_unit"],
            "package_price": p["package_price"], "source": "owner_confirmed", "source_url": None, "evidence": _evidence(request)})],
        "register_purchase": lambda: [("register_purchase", {
            "dish_id": p["dish_id"], "ingredient_name": p["ingredient"], "kind": p["kind"], "packages": p["packages"],
            "package_quantity": p["package_quantity"], "package_unit": p["package_unit"], "package_price": p["package_price"],
            "price_source": p["price_source"], "source_url": p.get("source_url"), "evidence": _evidence(request)})],
        "adjust_budget": lambda: [("adjust_budget", {"delta": p["delta"], "evidence": _evidence(request)})],
        "import_pantry_preview": lambda: [("import_pantry", {"file_path": p["file_path"], "apply": False})],
        "import_pantry_apply": lambda: [("import_pantry", {"import_id": p["import_id"], "apply": True})],
    }.get(task)
    if tool is None:
        return _recipe_calls(task, p, _evidence(request))
    return [(f"mcp__ledger__{name}", args) for name, args in tool()]


def _recipe_calls(task: str, p: dict, evidence: str) -> list[tuple[str, dict]] | None:
    """recipe_expert's own single-tool tasks; suggest_dishes and normalize_recipe stay with the model (they research)."""
    tool = {
        "record_kitchen_fact": lambda: [("update_kitchen_profile", {"key": p["key"], "numeric_value": p.get("numeric_value"),
                                                                    "status": p["status"], "evidence": evidence})],
        "reject_candidate": lambda: [("reject_candidate_dish", {"dish_id": p["dish_id"], "reason": p["reason"], "evidence": evidence})],
        "set_launch_batch": lambda: [("set_launch_batch_portions", {"dish_id": p["dish_id"],
                                                                    "launch_batch_portions": p["launch_batch_portions"], "evidence": evidence})],
        "confirm_requirement": lambda: [("confirm_dish_requirement", {"dish_id": p["dish_id"], "requirement": p["requirement"],
                                                                      "status": p["status"], "evidence": evidence})],
        "confirm_measure": lambda: [("confirm_measure", {"ingredient_name": p["ingredient_name"], "measure": p["measure"],
                                                         "evidence": evidence})],
        "accept": lambda: [("check_viability", {"dish_id": p["dish_id"]}), ("accept_dish", {"dish_id": p["dish_id"], "evidence": evidence})],
    }.get(task)
    return [(f"mcp__ledger__{name}", args) for name, args in tool()] if tool else None


REPLY_KEY = {"record_kitchen_fact": "kitchen_fact", "reject_candidate": "dish", "set_launch_batch": "dish",
             "confirm_requirement": "requirement", "confirm_measure": "measure", "accept": "dish"}


def _reply_result(task: str, result: dict) -> dict:
    """The result as contracts/experts/recipe_expert.response.json describes it: kitchen-ledger names a couple of these
    fields differently, and the peer rejects the reply when they travel raw."""
    if task == "record_kitchen_fact":
        return {"kitchen_fact": {"key": result["requirement_key"], "status": result["status"]}}
    if task == "set_launch_batch":
        match = result["pantry_match"]  # set_launch_batch_portions refuses any status but candidate
        return {"dish": {"dish_id": result["dish_id"], "status": "candidate", "pantry_coverage_pct": match["pantry_coverage_pct"],
                         "missing_ingredients": [item["ingredient"] for item in match["missing"]]}}
    key = REPLY_KEY.get(task)
    return {key: result} if key else result


def answer(request, call_tool) -> dict | None:
    """The A2A reply for a deterministic task, or None when the model should handle the request."""
    try:
        calls = _calls(request) if isinstance(request, dict) else None
    except (KeyError, TypeError):
        return None  # the contract was checked by the caller; anything unexpected goes to the model
    if not calls:
        return None
    result = None
    for tool, args in calls:
        result = call_tool(tool, args)
        if not isinstance(result, dict) or "error" in result:
            return None
    try:
        shaped = _reply_result(request.get("task"), result)
    except (KeyError, TypeError):
        return None  # an unexpected payload is the model's problem, not a reply the peer will reject
    return {"result": shaped, "questions_for_owner": [], "cost_usd_spent": 0}


def _text(content) -> str:
    if isinstance(content, str):
        return content
    return "\n".join(block.get("text", "") for block in content or [] if isinstance(block, dict) and block.get("type") == "text")


def _a2a_request(llm_request) -> dict | None:
    for message in reversed((llm_request or {}).get("messages") or []):
        if message.get("role") == "user":
            text = _text(message.get("content"))
            try:
                data = json.JSONDecoder().raw_decode(text[text.index("{"):])[0]
            except ValueError:
                return None
            return data if isinstance(data, dict) and "task" in data else None
    return None


def _tool_caller(session_id: str, task_id: str):
    """kitchen-ledger through Hermes' own dispatch, so allowlist, trace, relay and telemetry hooks all still run."""
    import model_tools

    from .relay import _tool_payload

    return lambda tool, args: _tool_payload(model_tools.handle_function_call(tool, args, task_id, session_id=session_id))


def _synthetic(text: str, model: str):
    from anthropic.types import Message, TextBlock, Usage

    return Message(id="msg_kitchen_fast_path", type="message", role="assistant", model=model or "kitchen-fast-path",
                   content=[TextBlock(type="text", text=text)], stop_reason="end_turn", stop_sequence=None,
                   usage=Usage(input_tokens=0, output_tokens=0))


def llm_execution(request=None, next_call=None, api_call_count=0, platform="", session_id="", task_id="", model="", **_):
    if api_call_count == 1 and platform != "subagent":
        try:
            reply = answer(_a2a_request(request), _tool_caller(session_id, task_id))
        except Exception:
            log.exception("kitchen_a2a fast path failed; the model handles the request")
            reply = None
        if reply is not None:
            return _synthetic(json.dumps(reply, ensure_ascii=False), model)
    return next_call(request)
