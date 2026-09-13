"""PL9 lever 1: cost_expert answers single-tool tasks without a model loop; tasks that need judgment still go to the model."""

import json

import pytest

from kitchen_a2a import fast_path

CONFIRMATION = {"choice": "Confirmar", "summary": "Comprar 1 pacote de 2 kg de tomate por R$ 16,00"}


def request(task, payload, confirmation=None, statement=None):
    return {"task": task, "trace": {"trace_id": "t", "parent_span_id": None, "turn_cost_remaining_usd": 4.0},
            "owner_confirmation": confirmation, "owner_statement": statement, "payload": payload}


class FakeTools:
    def __init__(self, results):
        self.results, self.calls = results, []

    def __call__(self, tool, args):
        self.calls.append((tool, args))
        return self.results[tool]


def test_budget_fit_is_one_tool_call_and_the_reply_carries_its_result():
    # Live eval trial: ask_cost_expert took 23 s at p50 while the costs-mcp call itself took ~0.1 s.
    tools = FakeTools({"mcp__costs__check_budget_fit": {"fits": True, "budget_remaining_display": "R$ 80,00"}})
    assert fast_path.answer(request("budget_fit", {"dish_id": 2}), tools) == {
        "result": {"fits": True, "budget_remaining_display": "R$ 80,00"}, "questions_for_owner": [], "cost_usd_spent": 0}
    assert tools.calls == [("mcp__costs__check_budget_fit", {"dish_id": 2})]


def test_match_and_cost_checks_the_pantry_then_computes_the_cost():
    tools = FakeTools({"mcp__costs__check_pantry_match": {"have": []}, "mcp__costs__compute_dish_cost": {"lines": []}})
    assert fast_path.answer(request("match_and_cost", {"dish_id": 2}), tools)["result"] == {"lines": []}
    assert [tool for tool, _ in tools.calls] == ["mcp__costs__check_pantry_match", "mcp__costs__compute_dish_cost"]


PURCHASE = {"dish_id": 5, "ingredient": "Tomate", "kind": "food", "packages": 1, "package_quantity": "2", "package_unit": "kg",
            "package_price": "16.00", "price_source": "owner_confirmed", "source_url": None}


@pytest.mark.parametrize("task, payload, confirmation, statement, tool, args", [
    ("select_price_scenario", {"dish_id": 2, "target_cmv_pct": "0.30"}, CONFIRMATION, None,
     "mcp__costs__select_price_scenario", {"dish_id": 2, "target_cmv_pct": "0.30"}),
    ("simulate_promotion", {"dish_id": 2, "discount_pct": "0.15"}, None, None,
     "mcp__costs__simulate_promotion", {"dish_id": 2, "discount_pct": "0.15"}),
    ("correct_price", {"ingredient": "Tomate", "total_price_paid": "18.00", "quantity": "2", "unit": "kg"}, None, "paguei 18 reais",
     "mcp__costs__correct_price", {"ingredient_name": "Tomate", "total_price_paid": "18.00", "quantity": "2", "unit": "kg", "evidence": "paguei 18 reais"}),
    ("confirm_price_quote", {"ingredient": "Creme de leite", "package_quantity": "200", "package_unit": "g", "package_price": "2.99"}, CONFIRMATION, None,
     "mcp__costs__record_price_quote", {"ingredient_name": "Creme de leite", "kind": "food", "package_quantity": "200", "package_unit": "g",
                                         "package_price": "2.99", "source": "owner_confirmed", "source_url": None, "evidence": CONFIRMATION["summary"]}),
    ("register_purchase", PURCHASE, CONFIRMATION, None, "mcp__costs__register_purchase",
     {**{k: v for k, v in PURCHASE.items() if k != "ingredient"}, "ingredient_name": "Tomate", "evidence": CONFIRMATION["summary"]}),
    ("adjust_budget", {"delta": "10.00"}, CONFIRMATION, None, "mcp__costs__adjust_budget", {"delta": "10.00", "evidence": CONFIRMATION["summary"]}),
    ("import_pantry_preview", {"file_path": "/opt/data/cache/documents/despensa.xlsx"}, None, None,
     "mcp__costs__import_pantry", {"file_path": "/opt/data/cache/documents/despensa.xlsx", "apply": False}),
    ("import_pantry_apply", {"import_id": 3}, CONFIRMATION, None, "mcp__costs__import_pantry", {"import_id": 3, "apply": True}),
])
def test_single_tool_tasks_map_their_payload_to_the_tool(task, payload, confirmation, statement, tool, args):
    tools = FakeTools({tool: {"ok": True}})
    assert fast_path.answer(request(task, payload, confirmation, statement), tools)["result"] == {"ok": True}
    assert tools.calls == [(tool, args)]


def test_a_click_required_task_without_the_click_goes_to_the_model():
    tools = FakeTools({})
    assert fast_path.answer(request("select_price_scenario", {"dish_id": 2, "target_cmv_pct": "0.30"}), tools) is None
    assert fast_path.answer(request("register_purchase", PURCHASE), tools) is None and tools.calls == []


def test_tasks_that_need_judgment_or_research_go_to_the_model():
    tools = FakeTools({})
    assert fast_path.answer(request("price_missing_item", {"dish_id": 2, "ingredient": "Creme de leite"}), tools) is None
    assert fast_path.answer({"not": "a request"}, tools) is None and tools.calls == []


def test_a_tool_error_goes_back_to_the_model_to_phrase_the_questions():
    # An error means nothing was written, so the model may repeat the call and ask Dona Maria what is missing.
    tools = FakeTools({"mcp__costs__check_budget_fit": {"error": {"code": "missing_price_quote", "message": "quote these first"}}})
    assert fast_path.answer(request("budget_fit", {"dish_id": 2}), tools) is None


def test_the_middleware_answers_on_the_first_model_call_only(monkeypatch):
    tools = FakeTools({"mcp__costs__check_budget_fit": {"fits": True}})
    monkeypatch.setattr(fast_path, "_synthetic", lambda text, model: {"synthetic": json.loads(text)})
    monkeypatch.setattr(fast_path, "_tool_caller", lambda session_id, task_id: tools)
    model_calls = []
    message = {"messages": [{"role": "user", "content": "A2A request:\n" + json.dumps(request("budget_fit", {"dish_id": 2}))}]}

    def next_call(llm_request):
        model_calls.append(llm_request)
        return "model"

    kwargs = dict(request=message, next_call=next_call, platform="a2a", session_id="s", task_id="t", model="m")
    assert fast_path.llm_execution(api_call_count=1, **kwargs) == {"synthetic": {"result": {"fits": True}, "questions_for_owner": [], "cost_usd_spent": 0}}
    assert model_calls == []
    assert fast_path.llm_execution(api_call_count=2, **kwargs) == "model"
