"""Output verifier on orchestrator (D12): deterministic R$ grounding, then the Haiku policy. uncertain or any failure blocks,
and the whole body always returns a string, because Hermes delivers the unverified original when a hook raises.
"""

from .messages import INFRA_BLOCK_MESSAGE, NUMBER_BLOCK_MESSAGE, SCOPE_BLOCK_MESSAGE


def review(text: str, grounding, classify, *, platform: str) -> str | None:
    if platform == "subagent":
        return None
    try:
        if grounding.ungrounded(text or ""):
            return NUMBER_BLOCK_MESSAGE  # an invented amount is not an off-topic message; say so in her words
        verdict = classify(text or "").verdict
    except Exception:
        return INFRA_BLOCK_MESSAGE
    return text if verdict == "allow" else SCOPE_BLOCK_MESSAGE
