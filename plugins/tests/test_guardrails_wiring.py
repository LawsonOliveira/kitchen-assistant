"""kitchen_guardrails wired into Hermes on orchestrator: the Confirmar click reaches the ledger through the hook Hermes fires for
clarify (open question 10). clarify is an inline agent tool, so Hermes runs pre_tool_call and post_tool_call for it but
never transform_tool_result (agent/inline_tool_executors.py in the pinned image)."""

import json

import pytest

import kitchen_guardrails
from kitchen_guardrails.tool_policy import CLICK_REQUIRED_MESSAGE

CONFIRMATION = {"choice": "Confirmar", "summary": "Fixar o preço em R$ 9,90"}
CLARIFY_RESULT = json.dumps({"responses": [{"question": "Fixar o preço em R$ 9,90?", "choices_offered": ["Confirmar", "Cancelar"],
                                            "user_response": "Confirmar"}]}, ensure_ascii=False)


class FakeContext:
    def __init__(self):
        self.hooks, self.middleware, self.llm = {}, {}, None

    def register_hook(self, name, callback):
        self.hooks.setdefault(name, []).append(callback)

    def register_middleware(self, name, callback):
        self.middleware.setdefault(name, []).append(callback)


def fire(ctx, hook, **kwargs):
    return [callback(**kwargs) for callback in ctx.hooks.get(hook, [])]


@pytest.fixture
def orchestrator(monkeypatch):
    monkeypatch.setenv("KITCHEN_AGENT_ROLE", "orchestrator")
    monkeypatch.setenv("KITCHEN_GUARD_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("KITCHEN_TURN_COST_CAP_USD", "5.00")
    ctx = FakeContext()
    kitchen_guardrails.register(ctx)
    return ctx


CLICK_ARGS = {"task": "select_price_scenario", "payload": {"dish_id": 2}, "owner_confirmation": CONFIRMATION}


def ask_with_click(ctx, session_id="s1"):
    return fire(ctx, "pre_tool_call", tool_name="ask_cost_expert", session_id=session_id, args=CLICK_ARGS)


def not_sent(code):
    return json.dumps({"error": {"code": code, "message": "not sent", "details": {}}})


def test_a_confirmar_seen_by_post_tool_call_lets_one_click_required_request_through(orchestrator):
    fire(orchestrator, "post_tool_call", tool_name="clarify", args={}, result=CLARIFY_RESULT, session_id="s1")
    assert ask_with_click(orchestrator) == [None]
    assert ask_with_click(orchestrator) == [{"action": "block", "message": CLICK_REQUIRED_MESSAGE}]


@pytest.mark.parametrize("code", ["invalid_request", "missing_token"])
def test_a_request_refused_before_it_was_sent_gives_the_click_back(orchestrator, code):
    # Live scenario 01 rerun: the first request after Confirmar failed orchestrator's own contract check, was never sent, and
    # the corrected request was then blocked because the click had been spent on it.
    fire(orchestrator, "post_tool_call", tool_name="clarify", args={}, result=CLARIFY_RESULT, session_id="s1")
    assert ask_with_click(orchestrator) == [None]
    fire(orchestrator, "transform_tool_result", tool_name="ask_cost_expert", args=CLICK_ARGS, session_id="s1", result=not_sent(code))
    assert ask_with_click(orchestrator) == [None]
    assert ask_with_click(orchestrator) == [{"action": "block", "message": CLICK_REQUIRED_MESSAGE}]


def test_a_refused_request_without_owner_confirmation_gives_no_click(orchestrator):
    fire(orchestrator, "transform_tool_result", tool_name="ask_cost_expert", session_id="s1", result=not_sent("invalid_request"),
         args={"task": "compute_dish_cost", "payload": {"dish_id": 2}})
    assert ask_with_click(orchestrator) == [{"action": "block", "message": CLICK_REQUIRED_MESSAGE}]


def test_a_request_that_reached_the_expert_keeps_the_click_spent(orchestrator):
    fire(orchestrator, "post_tool_call", tool_name="clarify", args={}, result=CLARIFY_RESULT, session_id="s1")
    assert ask_with_click(orchestrator) == [None]
    fire(orchestrator, "transform_tool_result", tool_name="ask_cost_expert", args=CLICK_ARGS, session_id="s1",
         result=json.dumps({"result": {"error": {"code": "not_accepted"}}, "questions_for_owner": [], "cost_usd_spent": 0.01}))
    assert ask_with_click(orchestrator) == [{"action": "block", "message": CLICK_REQUIRED_MESSAGE}]


def test_without_a_clarify_the_click_required_request_is_blocked(orchestrator):
    assert ask_with_click(orchestrator) == [{"action": "block", "message": CLICK_REQUIRED_MESSAGE}]


def test_the_owner_message_of_each_turn_grounds_her_own_amounts(orchestrator, monkeypatch):
    from kitchen_guardrails import classifier
    from kitchen_guardrails.messages import NUMBER_BLOCK_MESSAGE

    monkeypatch.setattr(classifier, "classify", lambda *args, **kwargs: classifier.Verdict("allow", "", ""))
    fire(orchestrator, "pre_llm_call", session_id="s1", turn_id="t1", user_message="paguei R$ 2,99 na caixinha", platform="api_server")
    echo = "Vou registrar a caixinha por R$ 2,99, pode confirmar?"
    assert fire(orchestrator, "transform_llm_output", response_text=echo, session_id="s1", platform="api_server") == [echo]
    assert fire(orchestrator, "transform_llm_output", response_text="O total fica R$ 5,98.", session_id="s1",
                platform="api_server") == [NUMBER_BLOCK_MESSAGE]


def test_the_input_guard_runs_alongside_the_first_model_call(orchestrator, monkeypatch):
    # PL9 lever 4: each classification takes 2–5 s; an allowed turn should not wait for it before calling the model.
    import time

    from kitchen_guardrails import classifier

    events = []

    def slow_classify(*args, **kwargs):
        events.append("classify-start")
        time.sleep(0.3)
        events.append("classify-end")
        return classifier.Verdict("allow", "", "")

    def next_call(llm_request):
        events.append("model")
        return "model-response"

    monkeypatch.setattr(classifier, "classify", slow_classify)
    middleware = orchestrator.middleware["llm_execution"][0]
    llm_request = {"messages": [{"role": "user", "content": "quero um arroz com frango"}]}
    assert middleware(request=llm_request, next_call=next_call, api_call_count=1, platform="cli", session_id="s1", model="m") == "model-response"
    assert events.index("model") < events.index("classify-end")


def test_a_blocked_turn_discards_the_model_answer(orchestrator, monkeypatch):
    import kitchen_guardrails
    from kitchen_guardrails import classifier
    from kitchen_guardrails.messages import SCOPE_BLOCK_MESSAGE

    monkeypatch.setattr(classifier, "classify", lambda *args, **kwargs: classifier.Verdict("block", "out_of_scope", ""))
    monkeypatch.setattr(kitchen_guardrails, "_synthetic", lambda text, model: {"synthetic": text})
    middleware = orchestrator.middleware["llm_execution"][0]
    llm_request = {"messages": [{"role": "user", "content": "me ajuda com meu código python"}]}
    assert middleware(request=llm_request, next_call=lambda r: "model-response", api_call_count=1, platform="cli",
                      session_id="s1", model="m") == {"synthetic": SCOPE_BLOCK_MESSAGE}
