"""Haiku classification for the guards (D11, D15), fail loud: any timeout, network or parse problem is GuardInfraError.

Model access goes through Hermes' plugin LLM client (open question 2's approved route): the same Claude Code
credentials the agents use, no separate API key. The model override is allowed only for this plugin in config
(plugins.entries.sabor_guardrails.llm).
"""

import hashlib
import json
from collections import namedtuple
from pathlib import Path

GUARD_MODEL = "claude-haiku-4-5-20251001"
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
HOOK_LIMIT_SECONDS = 30  # Hermes skips a hook callback after 30 s, so a guard must answer before that
VERDICTS = ("allow", "block", "uncertain")
VERDICT_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["verdict", "category", "reason"],
    # No maxLength: Hermes validates the model's JSON against this schema, and a long label must not cost the verdict.
    "properties": {"verdict": {"enum": list(VERDICTS)}, "category": {"type": "string"}, "reason": {"type": "string"}},
}
CATEGORY_CHARS, REASON_CHARS = 40, 300
Verdict = namedtuple("Verdict", "verdict category reason")


class GuardInfraError(RuntimeError):
    """The classifier could not give a verdict: the guard must block with INFRA_BLOCK_MESSAGE."""


def guard_timeout_seconds(environ) -> float:
    """SABOR_GUARD_TIMEOUT_SECONDS is required and must stay below the hook limit, or the plugin refuses to load."""
    raw = (environ.get("SABOR_GUARD_TIMEOUT_SECONDS") or "").strip()
    try:
        seconds = float(raw)
    except ValueError:
        raise ValueError("SABOR_GUARD_TIMEOUT_SECONDS must be set to a number of seconds below 30") from None
    if not 0 < seconds < HOOK_LIMIT_SECONDS:
        raise ValueError(f"SABOR_GUARD_TIMEOUT_SECONDS={raw} must be above 0 and below {HOOK_LIMIT_SECONDS}")
    return seconds


def prompt_hash(prompt_file: str) -> str:
    return hashlib.sha256((PROMPTS_DIR / prompt_file).read_bytes()).hexdigest()


def parse_verdict(text) -> Verdict:
    data = text if isinstance(text, dict) else None
    if data is None:
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            raise GuardInfraError("classifier output is not JSON") from None
    if not isinstance(data, dict) or data.get("verdict") not in VERDICTS:
        raise GuardInfraError(f"classifier output has no valid verdict: {str(data)[:120]}")
    return Verdict(data["verdict"], str(data.get("category", ""))[:CATEGORY_CHARS], str(data.get("reason", ""))[:REASON_CHARS])


def classify(llm, prompt_file: str, content: str, timeout_s: float) -> Verdict:
    """One structured Haiku call; `llm` is the plugin's ctx.llm (PluginLlm)."""
    try:
        result = llm.complete_structured(
            instructions=(PROMPTS_DIR / prompt_file).read_text(encoding="utf-8"), input=[{"type": "text", "text": content}],
            json_schema=VERDICT_SCHEMA, schema_name="verdict", model=GUARD_MODEL, timeout=timeout_s, temperature=0,
            purpose=f"sabor_guardrails:{prompt_file}")
    except Exception as error:  # timeout, network, trust or provider errors: no verdict
        raise GuardInfraError(f"{type(error).__name__}: {error}") from error
    return parse_verdict(result.parsed if result.parsed is not None else result.text)
