"""Output verifier on orchestrator (D12): deterministic R$ grounding, then the Haiku policy. uncertain or any failure blocks,
and the whole body always returns a string, because Hermes delivers the unverified original when a hook raises.
"""

from .messages import CLAIM_BLOCK_MESSAGE, INFRA_BLOCK_MESSAGE, NUMBER_BLOCK_MESSAGE, SCOPE_BLOCK_MESSAGE


def review(text: str, grounding, classify, *, platform: str) -> str | None:
    if platform == "subagent":
        return None
    try:
        if grounding.ungrounded(text or ""):
            return NUMBER_BLOCK_MESSAGE  # an invented amount is not an off-topic message; say so in her words
        decision = classify(text or "")
    except Exception:
        return INFRA_BLOCK_MESSAGE
    if decision.verdict == "allow":
        return text
    # The category names why: a promise the menu cannot make is answered as such, everything else as out of scope.
    return CLAIM_BLOCK_MESSAGE if "claim" in (decision.category or "").lower() else SCOPE_BLOCK_MESSAGE
