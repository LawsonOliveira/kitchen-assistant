"""researcher hooks: fixed task types, synchronous fan-out to web children, provenance of recipe URLs (D5, C17)."""

import dataclasses
import json
from types import SimpleNamespace

from sabor_a2a import researcher_hooks as hooks

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
    hooks.transform_tool_result(tool_name="web_extract", result='{"results": [{"url": "https://site.example\\/receita"}]}', session_id="session-1")
    other = dict(RECIPE, source_url="https://site.example/receita")
    reply = hooks.fan_out(FakeLifecycle(json.dumps(recipe), json.dumps(other)), Request, "session-1", "recipe_search", ["a", "b"])
    assert reply["results"] == [recipe, other]
