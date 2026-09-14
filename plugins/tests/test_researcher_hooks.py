"""researcher hooks: fixed task types, synchronous fan-out to web children, provenance of recipe URLs (D5, C17)."""

import dataclasses
import json
from types import SimpleNamespace

from kitchen_a2a import researcher_hooks as hooks

RECIPE = {
    "name": "Arroz com frango", "source_url": "https://receitas.example/arroz-com-frango", "yield_portions": 4,
    "prep_time_minutes": 45, "ingredients": [{"name": "Arroz", "quantity": 400, "unit": "g", "pantry_match": None}],
    "requirements": ["stove_burners>=2"],
}
FAKE = dict(RECIPE, name="Receita inventada", source_url="https://inventado.example/nao-existe")
PRICE = {"product": "Creme de leite 200 g", "package_quantity": 200, "package_unit": "g", "price": 3.49,
         "source_url": "https://mercado.example/creme-de-leite", "retrieved_at": "2026-09-13"}


@dataclasses.dataclass(frozen=True)
class Request:  # stand-in for agent.subagent_lifecycle.SubagentLaunchRequest (fields the fan-out uses)
    goal: str
    context: str | None = None
    model: str | None = None
    allowed_toolsets: tuple[str, ...] | None = None


class FakeLifecycle:
    """Each reply is a child's final text, or "FAILED" / "TIMEOUT"."""

    def __init__(self, *replies):
        self.replies, self.launched, self.cancelled = list(replies), [], []

    def launch(self, request):
        self.launched.append(request)
        return len(self.launched) - 1

    def wait(self, handle, *, timeout_seconds=None):
        return SimpleNamespace(timed_out=self.replies[handle] == "TIMEOUT")

    def result(self, handle):
        reply = self.replies[handle]
        return SimpleNamespace(terminal_state="FAILED" if reply == "FAILED" else "SUCCEEDED", summary=reply)

    def cancel(self, handle, *, reason):
        self.cancelled.append(handle)


def request(session_id, task_type, *items):
    hooks.pre_llm_call(session_id=session_id, user_message=json.dumps({"task_type": task_type, "items": list(items)}), platform="a2a")


def visit(session_id, url):
    # transform_tool_result, not post_tool_call: Hermes suppresses post_tool_call inside a running tool (the fan-out)
    assert hooks.transform_tool_result(tool_name="web_extract", result=json.dumps({"results": [{"url": url, "content": "..."}]}),
                                       session_id=session_id) is None  # the result reaches the child unchanged


def setup_function():
    hooks.reset()


def test_model_visible_delegation_is_always_blocked():
    # Hermes runs top-level model delegations in the background, so the A2A reply would leave before the children end.
    request("session-1", "recipe_search", "frango com arroz")
    assert hooks.pre_tool_call(tool_name="delegate_task", args={"goal": "a"}, session_id="session-1")["action"] == "block"
    assert hooks.pre_tool_call(tool_name="web_search", args={"query": "x"}, session_id="session-1") is None


def test_unknown_task_type_launches_nothing():
    request("session-1", "open_question", "qualquer coisa")
    lifecycle = FakeLifecycle()
    reply = hooks.fan_out(lifecycle, Request, "session-1", "open_question", ["qualquer coisa"])
    assert reply["error"]["code"] == "unknown_task_type" and lifecycle.launched == []


def test_task_type_must_match_the_a2a_request():
    request("session-1", "ingredient_price", "creme de leite 200 g")
    reply = hooks.fan_out(FakeLifecycle(json.dumps(RECIPE)), Request, "session-1", "recipe_search", ["frango"])
    assert reply["error"]["code"] == "unknown_task_type"


def test_one_web_child_per_item_with_the_item_schema_in_its_context():
    request("session-1", "recipe_search", "frango com arroz", "arroz de forno")
    visit("session-1", RECIPE["source_url"])
    lifecycle = FakeLifecycle(json.dumps(RECIPE), "```json\n" + json.dumps(RECIPE) + "\n```")
    reply = hooks.fan_out(lifecycle, Request, "session-1", "recipe_search", ["frango com arroz", "arroz de forno"])
    assert [r.allowed_toolsets for r in lifecycle.launched] == [("web",), ("web",)]
    assert "frango com arroz" in lifecycle.launched[0].goal and '"source_url"' in lifecycle.launched[0].context
    assert '"$ref": "https://' not in lifecycle.launched[0].context  # the child sees a self-contained schema
    assert reply == {"task_type": "recipe_search", "results": [RECIPE, RECIPE], "unverified_source": [], "cost_usd_spent": 0.0}


def test_invalid_failed_and_timed_out_children_are_dropped():
    request("session-1", "ingredient_price", "a", "b", "c", "d")
    lifecycle = FakeLifecycle(json.dumps(PRICE), "não achei o preço", "FAILED", "TIMEOUT")
    reply = hooks.fan_out(lifecycle, Request, "session-1", "ingredient_price", ["a", "b", "c", "d"])
    assert reply == {"task_type": "ingredient_price", "results": [PRICE], "cost_usd_spent": 0.0}
    assert lifecycle.cancelled == [3]


def test_recipe_with_an_unvisited_url_is_dropped():
    request("session-1", "recipe_search", "a", "b")
    visit("session-1", RECIPE["source_url"])
    reply = hooks.fan_out(FakeLifecycle(json.dumps(RECIPE), json.dumps(FAKE)), Request, "session-1", "recipe_search", ["a", "b"])
    assert reply["results"] == [RECIPE] and reply["unverified_source"] == [FAKE["source_url"]]


def test_urls_fetched_by_delegate_children_count_for_the_parent():
    request("session-1", "recipe_search", "a")
    hooks.subagent_start(parent_session_id="session-1", child_session_id="child-1")
    visit("child-1", RECIPE["source_url"])
    assert hooks.fan_out(FakeLifecycle(json.dumps(RECIPE)), Request, "session-1", "recipe_search", ["a"])["results"] == [RECIPE]


def test_urls_visited_in_another_request_do_not_count():
    visit("other", RECIPE["source_url"])
    request("session-1", "recipe_search", "a")
    assert hooks.fan_out(FakeLifecycle(json.dumps(RECIPE)), Request, "session-1", "recipe_search", ["a"])["results"] == []


def test_a_new_request_in_a_reused_session_starts_fresh():
    request("session-1", "recipe_search", "a")
    visit("session-1", RECIPE["source_url"])
    request("session-1", "recipe_search", "c")
    assert hooks.fan_out(FakeLifecycle(json.dumps(RECIPE)), Request, "session-1", "recipe_search", ["c"])["results"] == []


def test_retry_message_with_trailing_validation_errors_keeps_the_task_type():
    retry = (json.dumps({"task_type": "ingredient_price", "items": ["creme de leite 200 g"]})
             + "\n\nYour previous reply did not match the JSON contract: <root>: {'x': 1} is not valid. Reply again.")
    hooks.pre_llm_call(session_id="session-1", user_message=retry, platform="a2a")
    reply = hooks.fan_out(FakeLifecycle(json.dumps(PRICE)), Request, "session-1", "ingredient_price", ["creme de leite 200 g"])
    assert reply["results"] == [PRICE]


def test_second_fan_out_in_the_same_request_is_refused():
    request("session-1", "ingredient_price", "a")
    hooks.fan_out(FakeLifecycle(json.dumps(PRICE)), Request, "session-1", "ingredient_price", ["a"])
    lifecycle = FakeLifecycle(json.dumps(PRICE))
    assert hooks.fan_out(lifecycle, Request, "session-1", "ingredient_price", ["a"])["error"]["code"] == "already_called"
    assert lifecycle.launched == []


def test_final_reply_is_the_merged_fan_out_result_whatever_the_model_wrote():
    request("session-1", "ingredient_price", "a")
    merged = hooks.fan_out(FakeLifecycle(json.dumps(PRICE)), Request, "session-1", "ingredient_price", ["a"])
    assert json.loads(hooks.transform_llm_output(response_text="Pronto!", session_id="session-1", platform="a2a")) == merged
    assert hooks.transform_llm_output(response_text="{}", session_id="child-1", platform="subagent") is None


def test_visited_urls_with_parentheses_and_escaped_slashes_are_recognized():
    url = "http://www.example.com/recipe_pages/brazil/Rice_with_Chicken_(Arroz_com_frango).php"
    recipe = dict(RECIPE, source_url=url)
    request("session-1", "recipe_search", "a", "b")
    hooks.transform_tool_result(tool_name="web_search", result=json.dumps({"data": {"web": [{"url": url, "title": "x"}]}}), session_id="session-1")
    hooks.transform_tool_result(tool_name="web_extract", result='{"results": [{"url": "https://site.example\\/receita", "content": "Receita"}]}', session_id="session-1")
    other = dict(RECIPE, source_url="https://site.example/receita")
    reply = hooks.fan_out(FakeLifecycle(json.dumps(recipe), json.dumps(other)), Request, "session-1", "recipe_search", ["a", "b"])
    assert reply["results"] == [recipe, other]


LONG_NAME = dict(RECIPE, ingredients=[dict(RECIPE["ingredients"][0], name="peito de frango grande, sem pele e sem osso, cozido e desfiado")])


def test_a_schema_invalid_child_reply_gets_one_repair_child_with_the_errors():
    # Live run: 2 of 3 children were dropped for a 61-character ingredient name and a null quantity.
    request("session-1", "recipe_search", "a")
    visit("session-1", RECIPE["source_url"])
    lifecycle = FakeLifecycle(json.dumps(LONG_NAME), json.dumps(RECIPE))
    reply = hooks.fan_out(lifecycle, Request, "session-1", "recipe_search", ["a"])
    assert reply["results"] == [RECIPE] and len(lifecycle.launched) == 2
    repair = lifecycle.launched[1]
    assert "too long" in repair.context and LONG_NAME["ingredients"][0]["name"] in repair.context
    assert repair.allowed_toolsets == ("web",) and "never guess" in repair.goal


def test_a_repair_that_is_still_invalid_is_dropped():
    request("session-1", "recipe_search", "a")
    visit("session-1", RECIPE["source_url"])
    lifecycle = FakeLifecycle(json.dumps(LONG_NAME), json.dumps(LONG_NAME))
    assert hooks.fan_out(lifecycle, Request, "session-1", "recipe_search", ["a"])["results"] == []
    assert len(lifecycle.launched) == 2  # one repair only


def test_children_without_json_are_dropped_without_repair_and_logged(caplog):
    # Nothing to repair: asking a model to produce JSON from no data invites invented values.
    request("session-1", "ingredient_price", "a", "b", "c")
    lifecycle = FakeLifecycle("não achei o preço", "FAILED", "TIMEOUT")
    with caplog.at_level("WARNING"):
        assert hooks.fan_out(lifecycle, Request, "session-1", "ingredient_price", ["a", "b", "c"])["results"] == []
    assert len(lifecycle.launched) == 3
    assert [r.getMessage().split(": ", 1)[0] for r in caplog.records] == ["research child dropped (ingredient_price)"] * 3
    assert "not a JSON object" in caplog.text and "FAILED" in caplog.text and "timed out" in caplog.text


def test_a_url_that_web_extract_could_not_fetch_is_not_visited(monkeypatch):
    # web_extract answers blocked or failed URLs with an error entry that still carries the URL.
    monkeypatch.delenv("KITCHEN_WEB_FIXTURES_DIR", raising=False)
    request("session-1", "recipe_search", "a")
    failed = json.dumps({"results": [{"url": FAKE["source_url"], "title": "", "content": "", "error": "Blocked: private network"}]})
    assert hooks.transform_tool_result(tool_name="web_extract", args={"urls": [FAKE["source_url"]]}, result=failed, session_id="session-1") is None
    assert hooks.fan_out(FakeLifecycle(json.dumps(FAKE)), Request, "session-1", "recipe_search", ["a"])["results"] == []


def test_a_research_child_gets_a_few_web_calls_per_tool_then_answers_with_what_it_read():
    # PL9 lever 3: the paused eval trial spent 120 Haiku calls on a handful of research children. Hermes launches lifecycle
    # children with its fixed DEFAULT_MAX_ITERATIONS (SubagentLaunchRequest has no iteration field, and
    # delegation.max_iterations only applies to delegate_task), so the cap is enforced here, per child and per web tool.
    request("session-1", "recipe_search", "frango com arroz")
    hooks.subagent_start(parent_session_id="session-1", child_session_id="child-1")
    for _ in range(3):
        assert hooks.pre_tool_call(tool_name="web_search", args={"query": "x"}, session_id="child-1") is None
    assert hooks.pre_tool_call(tool_name="web_search", args={"query": "x"}, session_id="child-1")["action"] == "block"
    assert hooks.pre_tool_call(tool_name="web_extract", args={"urls": ["https://a.example"]}, session_id="child-1") is None
    for _ in range(5):  # researcher itself is never capped
        assert hooks.pre_tool_call(tool_name="web_search", args={"query": "x"}, session_id="session-1") is None


def test_the_measure_lookup_child_asks_for_the_package_content_not_a_nutrition_serving():
    # Full run, scenario 01 trial 2: a measure_lookup answered "1 peito de frango (pacote) = 90 g" — a nutrition label
    # serving — the owner confirmed it, and the dish was priced at R$ 1,90 for ten portions.
    goal = hooks.CHILD_GOALS["measure_lookup"]
    assert "nutrition" in goal and "serving" in goal
