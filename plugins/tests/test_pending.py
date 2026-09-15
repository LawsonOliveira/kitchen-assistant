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


def test_the_next_question_is_appended_when_she_closes_with_something_open():
    # Hermes only calls pre_verify when the agent edited files (agent/turn_stop_gates.py), so the turn can never be
    # sent back in a conversation. The reply itself gets the question, in the hook the other guards already use.
    state = pending.Pending()
    state.read_tool_result("s1", {"result": {"dish": {"dish_id": 3, "status": "candidate"}}})
    reply = "Pronto, dona Maria! Os dois pratos já estão anotados certinhos. Vá descansar. 🌿"
    closed = pending.with_next_question(state, "s1", reply)
    assert closed.startswith(reply) and closed.rstrip().endswith("?")
    assert "aceitar" in closed.lower()

    asked = "Falta aceitar o prato — quer que eu aceite agora?"
    assert pending.with_next_question(state, "s1", asked) == asked  # she already asked something
    assert pending.with_next_question(pending.Pending(), "s1", reply) == reply  # nothing open


def test_the_question_names_what_is_open():
    state = pending.Pending()
    state.read_tool_result("s1", {"result": {"dish": {"dish_id": 3, "status": "accepted"}}})
    closed = pending.with_next_question(state, "s1", "Prontinho, tá tudo certo.")
    assert "preço" in closed.lower() and closed.rstrip().endswith("?")
