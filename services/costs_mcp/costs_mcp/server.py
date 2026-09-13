"""costs-mcp — deterministic pantry, CMV and pricing tools over MCP Streamable HTTP (PLAN.md D7).

Every request carries `Authorization: Bearer <agent token>` (COSTS_MCP_AGENT_TOKENS). The token decides the
agent, TOOL_PERMISSIONS decides what that agent may call (enforced here, not in prompts — D14), and every
call is written to audit_log.
"""

import hmac
import inspect
import logging
import os
import time
from pathlib import Path

import uvicorn
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from costs_mcp import db, operations, telemetry
from costs_mcp.pantry_import import seed_from_workbook

log = logging.getLogger("costs_mcp")

READ_TOOLS = {"get_pantry", "get_state_summary", "check_pantry_match", "get_launch_menu"}
TOOL_PERMISSIONS = {
    "fifi": READ_TOOLS,
    "recipe_expert": READ_TOOLS | {
        "check_viability", "register_candidate_dish", "reject_candidate_dish", "confirm_dish_requirement",
        "accept_dish", "update_kitchen_profile",
    },
    "cost_expert": READ_TOOLS | {
        "compute_dish_cost", "check_budget_fit", "simulate_promotion", "record_price_quote", "set_dish_packaging",
        "register_purchase", "adjust_budget", "correct_price", "set_conversion_factor", "select_price_scenario",
        "import_pantry",
    },
    "marketing_expert": READ_TOOLS | {"save_menu_copy", "register_promotion"},
}
TOOLS = {name: getattr(operations, name) for name in sorted(set().union(*TOOL_PERMISSIONS.values()))}
SERVER_INJECTED = {"conn", "import_dir"}  # never exposed to agents

mcp = MCPServer(name="costs", instructions="Deterministic pantry, CMV and pricing tools for Sabor da Maria.")
_agent_by_token: dict[str, str] = {}


def _dsn() -> str:
    return os.environ["DATABASE_URL"]


def _error(code: str, message: str, **details) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def dispatch(conn, agent: str, tool: str, args: dict, trace_id: str | None = None):
    """Permission check, call, commit or roll back, audit, telemetry. Returns the result or the MCP error shape."""
    started_at, started = telemetry.now(), time.monotonic()
    if tool not in TOOL_PERMISSIONS.get(agent, set()):
        result = _error("forbidden", f"{agent} may not call {tool}", agent=agent, tool=tool)
    else:
        operation = TOOLS[tool]
        kwargs = dict(args)
        if tool == "import_pantry":
            kwargs["import_dir"] = os.environ.get("SABOR_IMPORT_DIR", "/opt/data/cache/documents")
        try:
            inspect.signature(operation).bind(conn, **kwargs)
        except TypeError as error:
            result = _error("invalid_arguments", str(error), tool=tool)
        else:
            try:
                result = operation(conn, **kwargs)
                conn.commit()
            except operations.DomainError as error:
                conn.rollback()
                result = error.as_error()
    error_code = result["error"]["code"] if isinstance(result, dict) and "error" in result else None
    db.insert_audit(conn, agent, tool, args, result, error_code, trace_id)
    conn.commit()
    telemetry.after_call(conn, agent, tool, trace_id, started_at, started, error_code)  # best-effort cockpit events
    return result


def _agent_from_headers(headers) -> str:
    scheme, _, presented = (headers or {}).get("authorization", "").partition(" ")
    if scheme.lower() != "bearer":
        return "unknown"
    return next((agent for token, agent in _agent_by_token.items() if hmac.compare_digest(presented, token)), "unknown")


def _mcp_tool(name: str, operation):
    params = [p.replace(kind=inspect.Parameter.KEYWORD_ONLY) for p in inspect.signature(operation).parameters.values()
              if p.name not in SERVER_INJECTED]

    def tool(ctx: Context, **kwargs):
        trace_id = kwargs.pop("trace_id", None)
        with db.connect(_dsn()) as conn:
            return dispatch(conn, _agent_from_headers(ctx.headers), name, kwargs, trace_id)

    extra = [inspect.Parameter("trace_id", inspect.Parameter.KEYWORD_ONLY, default=None, annotation=str | None),
             inspect.Parameter("ctx", inspect.Parameter.KEYWORD_ONLY, annotation=Context)]
    tool.__signature__ = inspect.Signature(params + extra)
    tool.__annotations__ = {**{p.name: p.annotation for p in params if p.annotation is not inspect.Parameter.empty},
                            "trace_id": str | None, "ctx": Context}
    tool.__name__ = name
    tool.__doc__ = operation.__doc__
    return tool


for _name, _operation in TOOLS.items():
    mcp.add_tool(_mcp_tool(_name, _operation), name=_name, description=(_operation.__doc__ or _name).strip())


def parse_agent_tokens(raw: str) -> dict[str, str]:
    """`agent:token,agent:token` -> {token: agent}; empty or duplicated tokens fail loud."""
    tokens: dict[str, str] = {}
    for item in filter(None, (part.strip() for part in raw.split(","))):
        agent, _, token = item.partition(":")
        if not agent or not token or token in tokens:
            raise ValueError("COSTS_MCP_AGENT_TOKENS must be agent:token pairs with non-empty, distinct tokens")
        tokens[token] = agent
    if not tokens:
        raise ValueError("COSTS_MCP_AGENT_TOKENS is empty")
    return tokens


class BearerAuth:
    """ASGI wrapper: /health is open; everything else needs a known agent token."""

    def __init__(self, app, tokens: dict[str, str]):
        self.app = app
        self.tokens = tokens

    def _agent(self, scope) -> str | None:
        header = dict(scope.get("headers") or []).get(b"authorization", b"").decode()
        scheme, _, presented = header.partition(" ")
        if scheme.lower() != "bearer":
            return None
        return next((agent for token, agent in self.tokens.items() if hmac.compare_digest(presented, token)), None)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["path"] == "/health":
            return await JSONResponse({"status": "ok"})(scope, receive, send)
        if self._agent(scope) is None:
            return await JSONResponse(_error("unauthorized", "missing or unknown agent token"), status_code=401)(scope, receive, send)
        await self.app(scope, receive, send)


def main() -> None:
    # force=True: importing mcp installs a root handler first, which would swallow the level/logger prefix.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s", force=True)
    _agent_by_token.update(parse_agent_tokens(os.environ["COSTS_MCP_AGENT_TOKENS"]))
    with db.connect(_dsn()) as conn:
        db.apply_migrations(conn)
        loaded = seed_from_workbook(conn, Path(os.environ.get("SABOR_SPREADSHEET", "/data/despensa_dona_maria.xlsx")))
    log.info("seed loaded %d ingredients", loaded)
    security = TransportSecuritySettings(allowed_hosts=["costs-mcp:8000", "localhost:8000", "127.0.0.1:8000"])
    app = mcp.streamable_http_app(host="0.0.0.0", transport_security=security)
    uvicorn.run(BearerAuth(app, _agent_by_token), host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
