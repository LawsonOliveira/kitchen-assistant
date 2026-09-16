"""A question to Dona Maria goes through clarify, where her options are clickable (owner, 2026-09-16).

Live session: after the recipe expert answered, Dona Sálvia wrote "1. Lasanha… 2. Escondidinho… Gosta de cozinhar
alguma dessas?" in the reply text and ended the turn, so there was nothing to click ("agr nao retorna mais opções").
The prompt has said since the first loop that options live in `choices`; the model followed it two sessions out of
three. So the rule is in code (D47): a turn that ends asking her something is sent back to the model once, and the
answer that comes back with a clarify call is the one she sees.
"""

import kitchen_guardrails
from kitchen_guardrails import choices


class Block:
    def __init__(self, type, text=""):
        self.type, self.text = type, text


class Reply:
    def __init__(self, *blocks):
        self.content = list(blocks)


PROSE = Reply(Block("text", "Achei três opções:\n1. Lasanha\n2. Escondidinho\n\nGosta de alguma dessas?"))
CLARIFIED = Reply(Block("text", "Achei três opções:"), Block("tool_use"))
CLARIFIED.content[1].name = "clarify"
DONE = Reply(Block("text", "Pronto, anotei a lasanha."))
REQUEST = {"messages": [{"role": "user", "content": "1"}], "model": "m"}


def calls_returning(*replies):
    seen = []

    def next_call(request):
        seen.append(request)
        return replies[len(seen) - 1]

    return seen, next_call


def test_a_question_in_prose_is_asked_again_through_clarify():
    seen, next_call = calls_returning(CLARIFIED)
    assert choices.with_clarify(PROSE, REQUEST, next_call) is CLARIFIED
    assert len(seen) == 1
    messages = seen[0]["messages"]
    assert messages[:1] == REQUEST["messages"]  # the turn she started, plus what the model tried and the correction
    assert messages[-2]["role"] == "assistant" and "Gosta de alguma dessas?" in messages[-2]["content"]
    assert messages[-1]["role"] == "user" and "clarify" in messages[-1]["content"]


def test_a_reply_that_asks_nothing_is_left_alone():
    seen, next_call = calls_returning(CLARIFIED)
    assert choices.with_clarify(DONE, REQUEST, next_call) is DONE
    assert seen == []


def test_a_reply_that_already_asks_through_clarify_is_left_alone():
    seen, next_call = calls_returning(CLARIFIED)
    assert choices.with_clarify(CLARIFIED, REQUEST, next_call) is CLARIFIED
    assert seen == []


def test_the_model_is_asked_once_and_her_answer_is_never_lost():
    # If the second answer still has no clarify call, she reads the first one: a missing click beats a missing reply.
    seen, next_call = calls_returning(PROSE, CLARIFIED)
    assert choices.with_clarify(PROSE, REQUEST, next_call) is PROSE
    assert len(seen) == 1


def test_anything_that_is_not_a_provider_reply_passes_through():
    seen, next_call = calls_returning(CLARIFIED)
    assert choices.with_clarify("model-response", REQUEST, next_call) == "model-response"
    assert seen == []


def test_what_she_would_have_read_is_never_lost():
    # Owner (2026-09-16): "em nenhum momento falou que faltava tais ingredientes". The first answer carried the pantry
    # coverage and what is missing to buy; the retry came back with the clarify call and a one-line question, and she
    # read only that. The text she would have read is the model's first answer; the retry contributes its call.
    full = Reply(Block("text", "1. Lasanha - 69% da despensa. Falta comprar: creme de leite.\n\nGosta de alguma?"))
    short = Reply(Block("text", "Achei duas opções:"), Block("tool_use"))
    short.content[1].name = "clarify"
    seen, next_call = calls_returning(short)
    reply = choices.with_clarify(full, REQUEST, next_call)
    texts = [block.text for block in reply.content if block.type == "text"]
    assert texts == ["1. Lasanha - 69% da despensa. Falta comprar: creme de leite.\n\nGosta de alguma?"]
    assert [block.type for block in reply.content] == ["text", "tool_use"]
