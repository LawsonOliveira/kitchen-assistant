"""She never ends a turn without the next question while the ledger still has something open (full run, scenario 05)."""

from kitchen_guardrails import pending


def test_a_registered_dish_that_is_not_accepted_yet_is_pending():
    state = pending.Pending()
    state.read_tool_result("s1", {"result": {"dish": {"dish_id": 3, "status": "candidate"}}})
    assert state.open_for("s1") == "o prato registrado ainda não foi aceito"
    state.read_tool_result("s1", {"result": {"dish": {"dish_id": 3, "status": "accepted"}}})
    assert state.open_for("s1") == "o prato aceito ainda não tem preço"
    state.read_tool_result("s1", {"result": {"dish_id": 3, "display_price": "R$ 8,90"}})
    assert state.open_for("s1") is None


def test_a_reply_without_a_question_is_sent_back_only_while_something_is_open():
    state = pending.Pending()
    state.read_tool_result("s1", {"result": {"dish": {"dish_id": 3, "status": "candidate"}}})
    reply = "Pronto, Dona Maria! Já pode seguir pra próxima etapa quando quiser. 🌿"
    message = pending.continue_message(state, "s1", reply, attempt=0)
    assert message and "pergunta" in message and "o prato registrado ainda não foi aceito" in message

    asked = "Falta aceitar o prato — quer que eu aceite agora?"
    assert pending.continue_message(state, "s1", asked, attempt=0) is None  # she asked something
    assert pending.continue_message(state, "s1", reply, attempt=1) is None  # never twice in the same turn
    assert pending.continue_message(pending.Pending(), "s1", reply, attempt=0) is None  # nothing open
