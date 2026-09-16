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


def test_the_guard_shows_itself_working_before_its_verdict(orchestrator, monkeypatch):
    # The cockpit lit Dona Sálvia before the guard, as if the guard ran after her: the classification starts with the
    # model call but only published its event at the end. It says it is running when it starts (owner, 2026-09-16).
    import kitchen_guardrails
    from kitchen_guardrails import classifier

    events = []
    monkeypatch.setattr(kitchen_guardrails, "_emit", lambda kind, name, **fields: events.append((kind, fields.get("status"))))
    monkeypatch.setattr(classifier, "classify", lambda *args, **kwargs: classifier.Verdict("allow", "", ""))
    middleware = orchestrator.middleware["llm_execution"][0]
    request = {"messages": [{"role": "user", "content": "quero uma lasanha"}]}
    middleware(request=request, next_call=lambda r: "model-response", api_call_count=1, platform="cli",
               session_id="s3", model="m")
    assert events == [("guard_input", "running"), ("guard_input", "ok")]


def test_the_owner_message_is_classified_once(orchestrator, monkeypatch):
    # Live session: the same sentence was blocked at 01:12:55 and allowed at 01:13:00 — Hermes started the turn again
    # (an API retry) and the classifier, asked twice, answered differently. One owner message, one verdict.
    import kitchen_guardrails
    from kitchen_guardrails import classifier

    calls = []

    def classify(llm, prompt_file, content, timeout_s):
        calls.append(content)
        return classifier.Verdict("allow" if len(calls) == 1 else "block", "out_of_scope", "")

    monkeypatch.setattr(classifier, "classify", classify)
    monkeypatch.setattr(kitchen_guardrails, "_synthetic", lambda text, model: {"synthetic": text})
    middleware = orchestrator.middleware["llm_execution"][0]
    request = {"messages": [{"role": "user", "content": "oi, quero fazer uma lasanha, pesquise na internet"}]}
    call = dict(next_call=lambda r: "model-response", api_call_count=1, platform="cli", session_id="s1", model="m")
    assert middleware(request=request, **call) == "model-response"
    assert middleware(request=request, **call) == "model-response"  # the turn restarted; the verdict is the one taken
    # The restart comes back as a new turn, sometimes with a new session: what was judged is the exchange, not the turn.
    assert middleware(request=request, **{**call, "session_id": "s1-again"}) == "model-response"
    assert len(calls) == 1

    # "sim" after one question is not "sim" after another: the answer only means something next to what she was asked,
    # and caching it by the word alone made one bad verdict stick to every later yes.
    after = {"messages": [{"role": "assistant", "content": "Quer que eu calcule o preço?"}, {"role": "user", "content": "sim"}]}
    other = {"messages": [{"role": "assistant", "content": "Posso apagar sua despensa?"}, {"role": "user", "content": "sim"}]}
    middleware(request=after, **call)
    middleware(request=other, **call)
    assert len(calls) == 3


def test_a_turn_without_a_new_owner_message_is_not_classified(orchestrator, monkeypatch):
    # The guard exists to judge what Dona Maria typed; a turn that carries no new message of hers has nothing to judge.
    from kitchen_guardrails import classifier

    calls = []
    monkeypatch.setattr(classifier, "classify", lambda *args, **kwargs: calls.append(1) or classifier.Verdict("allow", "", ""))
    middleware = orchestrator.middleware["llm_execution"][0]
    request = {"messages": [{"role": "assistant", "content": "Achei três opções"}]}
    assert middleware(request=request, next_call=lambda r: "model-response", api_call_count=1, platform="cli",
                      session_id="s2", model="m") == "model-response"
    assert calls == []


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


def test_a_turn_that_ends_asking_her_in_prose_goes_back_to_the_model(orchestrator, monkeypatch):
    # The owner's session: the reply listed three dishes and asked which one, with nothing to click. The middleware
    # sends the turn back once so the question comes as a clarify call (kitchen_guardrails/choices.py).
    from kitchen_guardrails import classifier

    class Block:
        def __init__(self, type, **fields):
            self.type = type
            self.__dict__.update(fields)

    class Reply:
        def __init__(self, *blocks):
            self.content = list(blocks)

    prose = Reply(Block("text", text="1. Lasanha\n2. Escondidinho\n\nGosta de alguma dessas?"))
    clarified = Reply(Block("tool_use", name="clarify"))
    monkeypatch.setattr(classifier, "classify", lambda *args, **kwargs: classifier.Verdict("allow", "", ""))
    replies = [prose, clarified]
    middleware = orchestrator.middleware["llm_execution"][0]
    request = {"messages": [{"role": "user", "content": "quero a lasanha"}]}
    assert middleware(request=request, next_call=lambda r: replies.pop(0), api_call_count=1, platform="cli",
                      session_id="s9", model="m") is clarified
    assert replies == []


def test_the_reply_that_closes_a_turn_with_tools_is_checked_too(orchestrator):
    # The question she could not answer came after ask_recipe_expert, on the turn's second model call: the input guard
    # runs only on the first one, and the check for a prose question belongs to every call of the turn.
    class Block:
        def __init__(self, type, **fields):
            self.type = type
            self.__dict__.update(fields)

    class Reply:
        def __init__(self, *blocks):
            self.content = list(blocks)

    prose = Reply(Block("text", text="Achei três opções. Gosta de alguma dessas?"))
    clarified = Reply(Block("tool_use", name="clarify"))
    replies = [prose, clarified]
    middleware = orchestrator.middleware["llm_execution"][0]
    request = {"messages": [{"role": "user", "content": "quero a lasanha"}]}
    assert middleware(request=request, next_call=lambda r: replies.pop(0), api_call_count=2, platform="cli",
                      session_id="s10", model="m") is clarified


def test_a_broken_evidence_never_costs_her_the_question(orchestrator, monkeypatch):
    # Owner (2026-09-16): "as questões com clarify sumiram após sua mudança anterior". Whatever the guard wants to add
    # to a clarify, a failure in it must leave the question exactly as the model asked it.
    from kitchen_guardrails import approval

    monkeypatch.setattr(approval.Approvals, "with_evidence",
                        lambda self, session_id, question: (_ for _ in ()).throw(ValueError("boom")))
    args = {"questions": [{"question": "Aceitar o prato?", "choices": ["Confirmar", "Cancelar"]}]}
    assert fire(orchestrator, "pre_tool_call", tool_name="clarify", session_id="s11", args=args) == [None]


def test_the_clarify_the_agent_sees_carries_everything_the_guard_adds(orchestrator):
    # The guard had two ways in: `with_evidence`, question by question, and `clarify_with_evidence`, which also offers
    # "Ver a receita completa" and explains each dish. Only the first was wired, so the third choice and the pantry
    # lines existed in the tests and never in her session (owner, 2026-09-16: "o ver receita aparece em qual caso ?").
    import json as _json

    candidates = _json.dumps({"result": {"candidates": [
        {"recipe": {"name": "Escondidinho de carne moída"}, "pantry_coverage_pct": 64,
         "missing_ingredients": ["Milho", "Ervilha"]}]}}, ensure_ascii=False)
    recipe = {"task": "register_candidate", "payload": {"launch_batch_portions": 6, "recipe": {
        "name": "Escondidinho de carne moída", "yield_portions": 8, "prep_time_minutes": 40,
        "source_url": "https://exemplo.com/escondidinho",
        "ingredients": [{"name": "Carne moída", "quantity": 500, "unit": "g", "pantry_match": "Carne moída"}]}}}
    fire(orchestrator, "transform_tool_result", tool_name="ask_recipe_expert", args={}, result=candidates, session_id="s12")
    choice = fire(orchestrator, "pre_tool_call", tool_name="clarify", session_id="s12", args={"questions": [
        {"question": "Qual desses pratos a senhora gosta de cozinhar?", "choices": ["Escondidinho de carne moída"]}]})[0]
    assert "64% da despensa. Falta comprar: Milho, Ervilha." in choice["args"]["questions"][0]["question"]

    fire(orchestrator, "pre_tool_call", tool_name="ask_recipe_expert", session_id="s12", args=recipe)
    accept = fire(orchestrator, "pre_tool_call", tool_name="clarify", session_id="s12", args={"questions": [
        {"question": "Aceitar o Escondidinho de carne moída no cardápio?", "choices": ["Confirmar", "Cancelar"]}]})[0]
    assert accept["args"]["questions"][0]["choices"] == ["Confirmar", "Cancelar", "Ver a receita completa"]
