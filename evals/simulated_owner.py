"""Simulated Dona Maria for eval trials (PLAN.md Loop 6 step 3b).

Clarify prompts are answered deterministically from the scenario's clarify_answers; free text comes from a Haiku
persona that knows her profile, goal and behavior and reveals each fact only when Dona Fifi asks about it. Model calls
go through Hermes' auxiliary client inside the fifi container (open question 2): the same Claude Code credentials,
no separate API key.
"""

import json
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OWNER_MODEL = "claude-haiku-4-5-20251001"
END_MARKER = "FIM"


def _normalized(text) -> str:
    return " ".join(str(text).lower().split()).removesuffix(" (recommended)")


def clarify_answer(clarify_answers: list[dict], question: str) -> dict:
    """The first entry whose words all appear in the question wins; otherwise the default."""
    lowered = question.lower()
    for entry in clarify_answers:
        if "question_contains" in entry and all(word.lower() in lowered for word in entry["question_contains"]):
            return {key: entry[key] for key in ("choice", "choice_position") if key in entry}
    default = next((entry["default"] for entry in clarify_answers if "default" in entry), None)
    if default is None:
        raise ValueError(f"no clarify answer for {question!r} and no default")
    return {"choice": default}


def choice_index(answer: dict, choices: list[str]):
    """0-based index of the choice, or ("other", text) when the answer is not among the choices."""
    if "choice_position" in answer:
        return answer["choice_position"] - 1
    wanted = _normalized(answer["choice"])
    return next((index for index, choice in enumerate(choices) if _normalized(choice) == wanted), ("other", answer["choice"]))


def system_prompt(scenario: dict) -> str:
    profile = scenario["owner_profile"]
    behavior = "\n".join(f"- {item}" for item in profile.get("behavior", []))
    facts = "\n".join(f"- {fact['topic']}: {fact['answer']}" for fact in scenario.get("facts_to_reveal_only_if_asked", []))
    return f"""You play {profile['name']}, a restaurant owner, talking to her kitchen assistant Dona Fifi in a test.
Persona: {" ".join(str(profile.get("persona", "")).split())}
Goal: {profile.get("goal", "")}
Behavior:
{behavior}
Facts you know. Say each one only when Dona Fifi asks about its topic, in your own short words; never volunteer them:
{facts}
Rules: write one short message in colloquial Brazilian Portuguese, as {profile['name']}, never as the assistant. Never
invent facts beyond these; if asked something not covered, say you don't know. When your goal is reached and Dona Fifi
has nothing left to ask you, reply exactly {END_MARKER}."""


def next_message(llm, scenario: dict, transcript: list[dict]) -> str | None:
    """transcript: [{"speaker": "owner"|"fifi", "text"}]. None when the persona ends the conversation."""
    messages = [{"role": "assistant" if turn["speaker"] == "owner" else "user", "content": turn["text"]} for turn in transcript]
    text = llm(system_prompt(scenario), messages).strip()
    return None if text.upper() == END_MARKER else text


IN_FIFI = r'''
import json, sys
from agent.auxiliary_client import call_llm
request = json.load(sys.stdin)
response = call_llm(provider="anthropic", model=request["model"], messages=request["messages"],
                    max_tokens=request["max_tokens"], temperature=request["temperature"], timeout=120)
print("REPLY " + json.dumps({"text": response.choices[0].message.content,
                             "usage": getattr(response.usage, "__dict__", {})}, ensure_ascii=False))
'''


def container_llm(model: str = OWNER_MODEL, max_tokens: int = 400, temperature: float = 0.3):
    """llm(system, messages) -> text through Hermes' auxiliary client in the fifi container."""

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
            ["docker", "compose", "exec", "-T", "-u", "hermes", "-e", "HERMES_HOME=/opt/data", "-w", "/workspace", "fifi",
             "/opt/hermes/.venv/bin/python", "-c", IN_FIFI],
            input=json.dumps(request, ensure_ascii=False), capture_output=True, text=True, cwd=REPO, check=True)
        reply = next(line for line in completed.stdout.splitlines() if line.startswith("REPLY "))
        return json.loads(reply.removeprefix("REPLY "))["text"]

    return llm
