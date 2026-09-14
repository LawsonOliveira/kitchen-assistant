"""Simulated Dona Maria for eval trials (PLAN.md Loop 6 step 3b).

Clarify prompts are answered deterministically from the scenario's clarify_answers; free text comes from a Haiku
persona that knows her profile, goal and behavior and reveals each fact only when Dona Sálvia asks about it. Model calls
go through Hermes' auxiliary client inside the orchestrator container (open question 2): the same Claude Code credentials,
no separate API key.
"""

import json
import re
from decimal import Decimal
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OWNER_MODEL = "claude-haiku-4-5-20251001"
END_MARKER = "FIM"


def _normalized(text) -> str:
    return " ".join(str(text).lower().split()).removesuffix(" (recommended)")


def clarify_answer(clarify_answers: list[dict], question: str, choices: list[str] | None = None) -> dict:
    """The first entry whose words all appear in the question (and, with choices_count, that offers that many choices)
    wins; otherwise the default."""
    lowered = question.lower()
    for entry in clarify_answers:
        if "question_contains" not in entry or not all(word.lower() in lowered for word in entry["question_contains"]):
            continue
        if "choices_count" in entry and (choices is None or len(choices) != entry["choices_count"]):
            continue
        return {key: entry[key] for key in ("choice", "choice_position", "choice_contains", "choice_by_price") if key in entry}
    default = next((entry["default"] for entry in clarify_answers if "default" in entry), None)
    if default is None:
        raise ValueError(f"no clarify answer for {question!r} and no default")
    return {"choice": default}


_PRICE = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})")


def choice_index(answer: dict, choices: list[str]):
    """0-based index of the choice, or ("other", text) when the answer is not among the choices."""
    if "choice_position" in answer:
        return answer["choice_position"] - 1
    if "choice_contains" in answer:
        wanted = _normalized(answer["choice_contains"])
        return next((index for index, choice in enumerate(choices) if wanted in _normalized(choice)), ("other", answer["choice_contains"]))
    if "choice_by_price" in answer:
        # The three price scenarios come in whatever order Dona Sálvia listed them, so rank them by their own amount.
        priced = [(Decimal(match.group(1).replace(".", "").replace(",", ".")), index)
                  for index, choice in enumerate(choices) if (match := _PRICE.search(choice))]
        if len(priced) < 2:
            return ("other", answer["choice_by_price"])
        ranked = [index for _, index in sorted(priced)]
        wanted = answer["choice_by_price"]
        return ranked[0] if wanted == "cheapest" else ranked[-1] if wanted == "dearest" else ranked[len(ranked) // 2]
    wanted = _normalized(answer["choice"])
    return next((index for index, choice in enumerate(choices) if _normalized(choice) == wanted), ("other", answer["choice"]))


def system_prompt(scenario: dict) -> str:
    profile = scenario["owner_profile"]
    behavior = "\n".join(f"- {item}" for item in profile.get("behavior", []))
    facts = "\n".join(f"- {fact['topic']}: {fact['answer']}" for fact in scenario.get("facts_to_reveal_only_if_asked", []))
    return f"""You play {profile['name']}, a restaurant owner, talking to her kitchen assistant Dona Sálvia in a test.
Persona: {" ".join(str(profile.get("persona", "")).split())}
Goal: {profile.get("goal", "")}
Behavior:
{behavior}
Facts you know. Say each one only when Dona Sálvia asks about its topic, in your own short words; never volunteer them:
{facts}
Rules: write one short message in colloquial Brazilian Portuguese, as {profile['name']}, never as the assistant. Never
invent facts beyond these; if asked something not covered, say you don't know. Your pantry, prices and budget are already
in Dona Sálvia's system: never say you have or lack an ingredient unless a fact above says so. When your goal is reached
and Dona Sálvia has nothing left to ask you, reply exactly {END_MARKER}.
When the last line says she said nothing, she is still working on your request: ask her briefly how it is going, and
never end the conversation because she is silent."""


def _messages(transcript: list[dict]) -> list[dict]:
    """The persona speaks as the assistant role; Dona Sálvia is the other speaker. A transcript that ends with the owner
    (after a clarify she answered) would end the request with an assistant turn, which the model continues as a prefill
    and often answers with no text at all, so the silence is spelled out as Dona Sálvia's turn."""
    messages = [{"role": "assistant" if turn["speaker"] == "owner" else "user", "content": turn["text"]} for turn in transcript]
    if messages and messages[-1]["role"] == "assistant":
        messages.append({"role": "user", "content": "(Dona Sálvia não disse mais nada.)"})
    return messages


def next_message(llm, scenario: dict, transcript: list[dict]) -> str | None:
    """transcript: [{"speaker": "owner"|"orchestrator", "text"}]. None when the persona ends the conversation."""
    text = (llm(system_prompt(scenario), _messages(transcript)) or "").strip()
    if not text:
        return None  # a model reply without text content (it happens) ends the conversation instead of killing the run
    # The persona often appends the marker to a goodbye ("Obrigada mesmo! FIM"); only the upper-case word ends it.
    return None if text.upper() == END_MARKER or re.search(rf"(^|\s){END_MARKER}$", text) else text


def answer_clarify(llm, scenario: dict, transcript: list[dict], question: str, choices: list[str]) -> dict:
    """The scenario's clarify answer when it names one of the choices; otherwise the persona decides, as the owner would
    (a free-text clarify has no choices, so she always answers in her own words)."""
    answer = clarify_answer(scenario.get("clarify_answers") or [{"default": "Cancelar"}], question, choices)
    if choices:
        index = choice_index(answer, choices)
        if not isinstance(index, tuple) and 0 <= index < len(choices):
            return answer
    options = "\n".join(f"- {choice}" for choice in choices) or "(no buttons: answer in your own words)"
    prompt = (f"Dona Sálvia asks you, with buttons:\n{question}\nOptions:\n{options}\n"
              "Reply with exactly the text of one option, or a short answer in your own words if none fits.")
    return {"choice": (llm(system_prompt(scenario), _messages(transcript) + [{"role": "user", "content": prompt}]) or "").strip()}


IN_ORCHESTRATOR = r'''
import json, sys
from agent.auxiliary_client import call_llm
request = json.load(sys.stdin)
response = call_llm(provider="anthropic", model=request["model"], messages=request["messages"],
                    max_tokens=request["max_tokens"], temperature=request["temperature"], timeout=120)
print("REPLY " + json.dumps({"text": response.choices[0].message.content or "",
                             "usage": getattr(response.usage, "__dict__", {})}, ensure_ascii=False))
'''


def container_llm(model: str = OWNER_MODEL, max_tokens: int = 400, temperature: float = 0.3):
    """llm(system, messages) -> text through Hermes' auxiliary client in the orchestrator container."""

    def llm(system: str, messages: list[dict]) -> str:
        turns = []
        for message in [{"role": "user", "content": "(início da conversa)"}] + messages:
            if turns and turns[-1]["role"] == message["role"]:  # the provider needs alternating roles
                turns[-1]["content"] += "\n\n" + message["content"]
            else:
                turns.append(dict(message))
        request = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
                   "messages": [{"role": "system", "content": system}] + turns}
        completed = subprocess.run(
            ["docker", "compose", "exec", "-T", "-u", "hermes", "-e", "HERMES_HOME=/opt/data", "-w", "/workspace", "orchestrator",
             "/opt/hermes/.venv/bin/python", "-c", IN_ORCHESTRATOR],
            input=json.dumps(request, ensure_ascii=False), capture_output=True, text=True, cwd=REPO, check=True)
        reply = next(line for line in completed.stdout.splitlines() if line.startswith("REPLY "))
        return json.loads(reply.removeprefix("REPLY "))["text"]

    return llm
