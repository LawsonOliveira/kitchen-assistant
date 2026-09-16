"""Her questions come with something to click (owner, 2026-09-16: "agr nao retorna mais opções").

Dona Maria answers on a phone. A question written into the reply text gives her nothing to pick, and the options
enumerated there ("1. Lasanha 2. Escondidinho") are dead prose. The prompt says it, the model mostly does it, and the
turn it does not is a turn she cannot answer. So the check is in code: a turn that ends asking her something is sent
back to the model once, with her own question quoted, and only an answer that calls clarify replaces the first one.
"""

RETRY_INSTRUCTION = (
    "Your reply ends by asking Dona Maria something, but it ends the turn: she has nothing to click. Send the same "
    "reply again in the same words and numbers, and ask through the `clarify` tool in the same turn, one question per "
    "open point, with the options as `choices` (never enumerated in the text). Free-text questions go through clarify "
    "too, without choices."
)


def with_clarify(response, request, next_call):
    """The reply she sees: the prose question asked again through clarify, or the original when the retry did not."""
    question = _prose_question(response)
    if not question:
        return response
    messages = list((request or {}).get("messages") or [])
    retry = {**request, "messages": messages + [{"role": "assistant", "content": question},
                                                {"role": "user", "content": RETRY_INSTRUCTION}]}
    second = next_call(retry)
    return second if _calls_clarify(second) else response


def _prose_question(response) -> str:
    """The text of a final answer that asks her something without calling clarify; "" when there is nothing to fix."""
    blocks = getattr(response, "content", None)
    if not isinstance(blocks, list) or _calls_clarify(response):
        return ""
    text = "\n".join(getattr(block, "text", "") for block in blocks if getattr(block, "type", "") == "text")
    return text if "?" in text else ""


def _calls_clarify(response) -> bool:
    blocks = getattr(response, "content", None)
    if not isinstance(blocks, list):
        return False
    return any(getattr(block, "type", "") == "tool_use" and getattr(block, "name", "") == "clarify" for block in blocks)
