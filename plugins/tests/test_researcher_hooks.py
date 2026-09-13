"""researcher hooks: fixed task types, schema injection for delegate children, provenance of recipe URLs (D5)."""

import json

from sabor_a2a import researcher_hooks as hooks

RECIPE = {
    "name": "Arroz com frango", "source_url": "https://receitas.example/arroz-com-frango", "yield_portions": 4,
    "prep_time_minutes": 45, "ingredients": [{"name": "Arroz", "quantity": 400, "unit": "g", "pantry_match": None}],
    "requirements": ["stove_burners>=2"],
}
FAKE = dict(RECIPE, name="Receita inventada", source_url="https://inventado.example/nao-existe")


def reply(*recipes):
    return json.dumps({"task_type": "recipe_search", "results": list(recipes), "unverified_source": [], "cost_usd_spent": 0.01})


def setup_function():
    hooks.reset()


def test_unknown_task_type_blocks_delegation():
    hooks.remember_request("session-1", json.dumps({"task_type": "open_question", "items": ["qualquer coisa"]}))
    decision = hooks.pre_tool_call(tool_name="delegate_task", args={"goal": "responda"}, session_id="session-1")
    assert decision["action"] == "block"


def test_known_task_type_injects_a_self_contained_output_schema():
    hooks.remember_request("session-1", json.dumps({"task_type": "recipe_search", "items": ["frango com arroz"]}))
    decision = hooks.pre_tool_call(tool_name="delegate_task", args={"tasks": [{"goal": "a"}, {"goal": "b"}]}, session_id="session-1")
    assert decision["action"] == "modify"
    schemas = [task["output_schema"] for task in decision["args"]["tasks"]]
    assert all(schema["properties"]["source_url"] for schema in schemas)
    assert '"$ref": "https://' not in json.dumps(schemas)  # external refs inlined for Hermes' validator


def test_other_tools_are_not_touched():
    assert hooks.pre_tool_call(tool_name="web_search", args={"query": "x"}, session_id="session-1") is None


def test_recipe_with_an_unvisited_url_is_dropped():
    hooks.post_tool_call(tool_name="web_extract", result=json.dumps({"results": [{"url": RECIPE["source_url"], "content": "..."}]}),
                         session_id="session-1")
    filtered = json.loads(hooks.filter_final_response("session-1", reply(RECIPE, FAKE)))
    assert [r["source_url"] for r in filtered["results"]] == [RECIPE["source_url"]]
    assert filtered["unverified_source"] == [FAKE["source_url"]]


def test_urls_fetched_by_delegate_children_count_for_the_parent():
    hooks.subagent_start(parent_session_id="session-1", child_session_id="child-1")
    hooks.post_tool_call(tool_name="web_search", result=json.dumps({"results": [{"url": RECIPE["source_url"]}]}), session_id="child-1")
    filtered = json.loads(hooks.filter_final_response("session-1", reply(RECIPE)))
    assert filtered["unverified_source"] == []


def test_urls_visited_in_another_request_do_not_count():
    hooks.post_tool_call(tool_name="web_extract", result=json.dumps({"results": [{"url": RECIPE["source_url"]}]}), session_id="other")
    filtered = json.loads(hooks.filter_final_response("session-1", reply(RECIPE)))
    assert filtered["results"] == [] and filtered["unverified_source"] == [RECIPE["source_url"]]
