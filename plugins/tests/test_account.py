"""The account Dona Maria reads at a decision (probes A, B and C): the ledger writes it, the guard puts it in front of
the question. Three rounds of prompt changes could not make the model copy it."""

from kitchen_guardrails.account import RememberedAccounts, clarify_with_account, with_account
from kitchen_guardrails.grounding import SessionGrounding

CHAIN = "R$ 25,96 ÷ 10 porções = R$ 2,60 por porção"
MINIMUM = "R$ 2,60 ÷ 0,90 = R$ 2,89, porque o iFood fica com 10%"


def test_the_session_keeps_the_accounts_the_tools_returned():
    session = SessionGrounding()
    session.add_from_tool_result({"result": {"cost_chain_display": CHAIN, "cmv_per_portion_display": "R$ 2,60"}})
    assert session.chains == [CHAIN]


def test_a_question_that_shows_the_result_gets_the_account_in_front_of_it():
    question = "Fixar o preço em R$ 8,90? (custo R$ 2,60 por porção)"
    assert with_account(question, [CHAIN, MINIMUM]) == f"{CHAIN}. {question}"


def test_the_account_that_ends_in_another_amount_is_not_used():
    assert with_account("Quantas bocas do fogão ficam livres?", [CHAIN]) is None
    assert with_account("Registrar a compra de 1 pacote por R$ 16,00?", [CHAIN]) is None


def test_a_question_that_already_explains_itself_is_left_alone():
    assert with_account(f"{CHAIN}. Qual preço a senhora quer?", [CHAIN]) is None


def test_an_account_she_already_wrote_in_her_own_words_is_not_repeated():
    # Probe 20260915-075404: the injection worked and she also copied the minimum herself, so Dona Maria read
    # "R$ 2,72 ÷ 0,90 = R$ 3,02, porque o iFood fica com 10%. R$ 2,72 ÷ 0,90 = R$ 3,02 é o mínimo pra não perder
    # dinheiro." The same operation twice is exactly the padding the didactic criterion punishes.
    question = "R$ 2,60 ÷ 0,90 = R$ 2,89 é o mínimo pra não perder dinheiro. Qual preço a senhora quer?"
    assert with_account(question, [MINIMUM]) is None
    assert with_account(question, [CHAIN, MINIMUM]) == f"{CHAIN}. {question}"  # the other account is still new to her


def test_an_account_is_shown_once_per_session():
    # Live CLI session: the price question carried "R$ 34,91 ÷ 4 porções = R$ 8,73 por porção" and the confirmation
    # right after carried it again. Two steps of the same decision, the same arithmetic twice.
    memory = RememberedAccounts()
    first = {"questions": [{"question": "Qual preço a senhora quer fixar? (custo R$ 2,60 por porção)"}]}
    assert clarify_with_account(first, [CHAIN], memory)["questions"][0]["question"].startswith(CHAIN)
    again = {"questions": [{"question": "Fixar o preço em R$ 8,90? (custo R$ 2,60 por porção)"}]}
    assert clarify_with_account(again, [CHAIN], memory) is None  # she already read that account

    other = {"questions": [{"question": "Confirma a promoção? (lucro R$ 2,60 por porção)"}]}
    assert clarify_with_account(other, [MINIMUM], memory) is None  # a different account, but its result is not shown


def test_the_clarify_call_is_rewritten_question_by_question():
    args = {"questions": [{"question": "Fixar o preço em R$ 8,90? (custo R$ 2,60 por porção)", "choices": ["Confirmar", "Cancelar"]},
                          {"question": "Quantas porções no lote?", "choices": ["6", "10"]}]}
    modified = clarify_with_account(args, [CHAIN])
    assert modified["questions"][0]["question"].startswith(CHAIN)
    assert modified["questions"][1] == args["questions"][1]
    assert clarify_with_account(args, []) is None  # nothing learned yet, nothing to add
