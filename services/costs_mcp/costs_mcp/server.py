"""costs-mcp — deterministic pantry, CMV and pricing tools over MCP Streamable HTTP (PLAN.md D7).

Every request must carry `Authorization: Bearer <agent token>` (COSTS_MCP_AGENT_TOKENS). Loop 0 exposes
get_pantry and compute_dish_cost over the seeded spreadsheet; Loop 1 adds the full domain and per-agent
tool permissions.
"""

import hmac
import logging
import os
from decimal import Decimal
from pathlib import Path

import uvicorn
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from costs_mcp import db, pricing
from costs_mcp.pantry_import import seed_from_workbook

log = logging.getLogger("costs_mcp")

PLATFORM_FEE_RATE = Decimal(os.environ.get("SABOR_PLATFORM_FEE_RATE", "0.10"))
# Loop 0 accepts only metric/count recipe units; household measures arrive in Loop 1 (measures.py).
RECIPE_UNIT_TO_BASE = {
    "g": ("g", Decimal(1)),
    "kg": ("g", Decimal(1000)),
    "ml": ("ml", Decimal(1)),
    "l": ("ml", Decimal(1000)),
    "unit": ("unit", Decimal(1)),
}

mcp = MCPServer(name="costs", instructions="Deterministic pantry, CMV and pricing tools for Sabor da Maria.")


def _dsn() -> str:
    return os.environ["DATABASE_URL"]


def _error(code: str, message: str, **details) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


@mcp.tool()
def get_pantry() -> list[dict]:
    """Pantry ingredients: stock in base units (g, ml or unit) and unit cost from the current price."""
    with db.connect(_dsn()) as conn:
        rows = db.pantry_with_current_prices(conn)
    pantry = []
    for name, base_unit, stock, total_price_paid, quantity_purchased in rows:
        if total_price_paid is None:
            raise ValueError(f"{name} has no current price: unit cost cannot be derived")
        pantry.append({
            "name": name,
            "quantity_base": str(stock),
            "base_unit": base_unit,
            "unit_cost": str(pricing.unit_cost(total_price_paid, quantity_purchased)),
        })
    return pantry


@mcp.tool()
def compute_dish_cost(recipe: dict) -> dict:
    """CMV per portion, minimum price and a 30%-CMV price for a recipe whose ingredients all match the pantry."""
    lines = []
    with db.connect(_dsn()) as conn:
        for ingredient in recipe.get("ingredients") or []:
            name = ingredient.get("name")
            match = ingredient.get("pantry_match")
            if not match:
                return _error("unmatched_ingredient", f"{name!r} has no pantry match", ingredient=name)
            unit = ingredient.get("unit")
            if unit not in RECIPE_UNIT_TO_BASE:
                return _error("unsupported_unit", f"unit {unit!r} of {match!r} is not supported yet", ingredient=match, unit=unit)
            found = db.ingredient_with_current_price(conn, match)
            if found is None:
                return _error("unknown_ingredient", f"{match!r} is not in the pantry", ingredient=match)
            base_unit, total_price_paid, quantity_purchased = found
            recipe_base_unit, factor = RECIPE_UNIT_TO_BASE[unit]
            if recipe_base_unit != base_unit:
                return _error("incompatible_units", f"{match!r} is stocked in {base_unit}, recipe uses {unit}",
                              ingredient=match, stocked_in=base_unit, recipe_unit=unit)
            quantity_base = Decimal(str(ingredient["quantity"])) * factor
            lines.append((quantity_base, pricing.unit_cost(total_price_paid, quantity_purchased)))
    yield_portions = recipe.get("yield_portions")
    if not isinstance(yield_portions, int) or yield_portions <= 0:
        return _error("invalid_portions", f"yield_portions must be a positive integer, got {yield_portions!r}")
    if not lines:
        return _error("empty_recipe", "recipe has no ingredients")
    cmv_per_portion = pricing.recipe_cmv(lines) / yield_portions
    return {
        "cmv_per_portion": str(cmv_per_portion),
        "min_price": str(pricing.min_price(cmv_per_portion, PLATFORM_FEE_RATE)),
        "price_30pct": str(cmv_per_portion / Decimal("0.30")),
    }


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
        agent = self._agent(scope)
        if agent is None:
            response = JSONResponse(_error("unauthorized", "missing or unknown agent token"), status_code=401)
            return await response(scope, receive, send)
        scope.setdefault("state", {})["agent"] = agent
        await self.app(scope, receive, send)


def main() -> None:
    # force=True: importing mcp installs a root handler first, which would swallow the level/logger prefix.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s", force=True)
    tokens = parse_agent_tokens(os.environ["COSTS_MCP_AGENT_TOKENS"])
    with db.connect(_dsn()) as conn:
        db.apply_migrations(conn)
        loaded = seed_from_workbook(conn, Path(os.environ.get("SABOR_SPREADSHEET", "/data/despensa_dona_maria.xlsx")))
    log.info("seed loaded %d ingredients", loaded)
    security = TransportSecuritySettings(allowed_hosts=["costs-mcp:8000", "localhost:8000", "127.0.0.1:8000"])
    app = mcp.streamable_http_app(host="0.0.0.0", transport_security=security)
    uvicorn.run(BearerAuth(app, tokens), host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
