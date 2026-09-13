from conftest import EVIDENCE
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient

from costs_mcp import server

PURCHASE_ARGS = {
    "ingredient_name": "Marmita 500 ml", "kind": "packaging", "packages": 1, "package_quantity": "50",
    "package_unit": "un", "package_price": "25.00", "price_source": "owner_confirmed", "source_url": None,
    "dish_id": None, "evidence": EVIDENCE,
}


def last_audit(conn):
    return conn.execute("SELECT agent, tool, error_code FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()


def test_every_permitted_tool_exists():
    for agent, tools in server.TOOL_PERMISSIONS.items():
        assert set(tools) <= set(server.TOOLS), agent


def test_marketing_expert_cannot_register_purchases(conn):
    result = server.dispatch(conn, "marketing_expert", "register_purchase", PURCHASE_ARGS)
    assert result["error"]["code"] == "forbidden"
    assert last_audit(conn) == ("marketing_expert", "register_purchase", "forbidden")
    assert server.dispatch(conn, "cost_expert", "get_state_summary", {})["budget_remaining_display"] == "R$ 80,00"


def test_researcher_has_no_access_to_costs(conn):
    assert server.dispatch(conn, "researcher", "get_pantry", {})["error"]["code"] == "forbidden"


def test_permitted_call_is_audited(conn):
    result = server.dispatch(conn, "cost_expert", "register_purchase", PURCHASE_ARGS)
    assert "error" not in result
    assert last_audit(conn) == ("cost_expert", "register_purchase", None)


def test_domain_errors_use_the_mcp_error_shape_and_are_audited(conn):
    result = server.dispatch(conn, "cost_expert", "adjust_budget", {"delta": "0", "evidence": EVIDENCE})
    assert set(result["error"]) == {"code", "message", "details"}
    assert result["error"]["code"] == "invalid_delta"
    assert last_audit(conn) == ("cost_expert", "adjust_budget", "invalid_delta")


def test_unknown_token_is_rejected_before_reaching_the_mcp_app():
    client = TestClient(server.BearerAuth(PlainTextResponse("ok"), {"good-token": "fifi"}))
    assert client.get("/mcp").status_code == 401
    assert client.get("/mcp", headers={"Authorization": "Bearer not-a-token"}).status_code == 401
    assert client.get("/mcp", headers={"Authorization": "Bearer good-token"}).status_code == 200
    assert client.get("/health").status_code == 200


def test_only_recipe_expert_changes_a_candidate_launch_batch():
    assert "set_launch_batch_portions" in server.TOOL_PERMISSIONS["recipe_expert"]
    assert all("set_launch_batch_portions" not in tools for agent, tools in server.TOOL_PERMISSIONS.items() if agent != "recipe_expert")


def test_only_recipe_expert_records_and_confirms_measures():
    for tool in ("record_measure_quote", "confirm_measure"):
        assert tool in server.TOOL_PERMISSIONS["recipe_expert"]
        assert all(tool not in tools for agent, tools in server.TOOL_PERMISSIONS.items() if agent != "recipe_expert")


def test_only_recipe_expert_reads_and_fills_the_recipe_cache():
    for tool in ("find_cached_recipes", "cache_recipes"):
        assert tool in server.TOOL_PERMISSIONS["recipe_expert"]
        assert all(tool not in tools for agent, tools in server.TOOL_PERMISSIONS.items() if agent != "recipe_expert")
