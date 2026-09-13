"""Typed A2A tools between Sabor da Maria agents (PLAN.md D3, D6).

The call graph is fixed: fifi calls the three experts; the experts call researcher. Each container
declares its role in SABOR_AGENT_ROLE and presents its own caller token (SABOR_A2A_TOKEN).
Loop 0 is a plain-text passthrough; Loop 2 adds contract validation.
"""

import json
import logging
import os

log = logging.getLogger(__name__)

TOOLSET = "sabor_a2a"
RESEARCH_TASK_TYPES = ["recipe_search", "ingredient_price", "menu_reference"]

# role -> {tool name: (peer URL, timeout seconds, description)}
ROLE_TOOLS = {
    "fifi": {
        "ask_recipe_expert": ("http://recipe-expert:9900/", 450, "Ask the recipe expert (recipes, feasibility, kitchen facts)."),
        "ask_cost_expert": ("http://cost-expert:9900/", 450, "Ask the cost expert (pantry match, CMV, prices, budget)."),
        "ask_marketing_expert": ("http://marketing-expert:9900/", 450, "Ask the marketing expert (iFood menu copy, promotions)."),
    },
    "recipe_expert": {"research": ("http://researcher:9900/", 270, "Ask the web researcher for structured results.")},
    "cost_expert": {"research": ("http://researcher:9900/", 270, "Ask the web researcher for structured results.")},
    "marketing_expert": {"research": ("http://researcher:9900/", 270, "Ask the web researcher for structured results.")},
    "researcher": {},
}


def _error(code: str, message: str) -> str:
    return json.dumps({"error": {"code": code, "message": message, "details": {}}})


def _make_handler(tool_name: str, peer_url: str, timeout_s: int):
    def handler(args: dict, **_) -> str:
        from .client import A2AError, send_message

        if tool_name == "research":
            text = json.dumps({"task_type": args.get("task_type"), "payload": args.get("payload") or {}}, ensure_ascii=False)
        else:
            text = str(args.get("message") or "")
        if not text.strip():
            return _error("empty_request", f"{tool_name} needs a non-empty request")
        token = os.environ.get("SABOR_A2A_TOKEN", "")
        if not token:
            return _error("missing_token", "SABOR_A2A_TOKEN is not set in this container")
        try:
            return send_message(peer_url, token, text, timeout_s)
        except A2AError as error:
            return _error("a2a_failure", str(error))

    return handler


def _schema(tool_name: str, description: str) -> dict:
    if tool_name == "research":
        properties = {
            "task_type": {"type": "string", "enum": RESEARCH_TASK_TYPES},
            "payload": {"type": "object", "description": "Task input, e.g. {\"items\": [\"frango com arroz\"]}"},
        }
        required = ["task_type", "payload"]
    else:
        properties = {"message": {"type": "string", "description": "The request for the expert, in English."}}
        required = ["message"]
    return {"name": tool_name, "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required}}


def register(ctx) -> None:
    role = os.environ.get("SABOR_AGENT_ROLE", "")
    if role not in ROLE_TOOLS:
        log.error("sabor_a2a: SABOR_AGENT_ROLE=%r is not one of %s; no A2A tools registered", role, sorted(ROLE_TOOLS))
        return
    for tool_name, (peer_url, timeout_s, description) in ROLE_TOOLS[role].items():
        ctx.register_tool(name=tool_name, toolset=TOOLSET, schema=_schema(tool_name, description),
                          handler=_make_handler(tool_name, peer_url, timeout_s), description=description)
