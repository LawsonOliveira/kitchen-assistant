"""Per-agent tool allowlists in pre_tool_call (D13) and the deterministic click check (open question 10).

pre_tool_call is the only Hermes hook that fails closed, so the allowlist lives there on all five agents. On orchestrator,
an ask_* request that carries owner_confirmation needs an unused "Confirmar" answer from the latest clarify in the
same session; the LLM alone can no longer grant a write (C29 showed clarify answering itself in single-query mode).
"""

import json
import re
import threading

READ = ("get_pantry", "get_state_summary", "check_pantry_match", "get_launch_menu")
SKILLS = {"skill_view", "skills_list"}
ASK_TOOLS = {"ask_recipe_expert", "ask_cost_expert", "ask_marketing_expert"}


def _mcp(*tools: str) -> set[str]:
    return {f"mcp__ledger__{tool}" for tool in tools}


ALLOWED = {
    "orchestrator": {"clarify", "memory"} | ASK_TOOLS | SKILLS | _mcp(*READ),
    "recipe_expert": {"research"} | SKILLS | _mcp(*READ, "check_viability", "register_candidate_dish", "reject_candidate_dish", "set_launch_batch_portions", "record_measure_quote", "confirm_measure", "find_cached_recipes", "cache_recipes",
                                                  "confirm_dish_requirement", "accept_dish", "update_kitchen_profile"),
    "cost_expert": {"research"} | SKILLS | _mcp(*READ, "compute_dish_cost", "check_budget_fit", "simulate_promotion",
                                                "record_price_quote", "set_dish_packaging", "register_purchase", "adjust_budget",
                                                "correct_price", "set_conversion_factor", "select_price_scenario", "import_pantry"),
    "marketing_expert": {"research"} | SKILLS | _mcp(*READ, "save_menu_copy", "register_promotion"),
    # fan_out_research replaced model-issued delegation (PLAN.md C17); the web children run under this role too.
    "researcher": {"web_search", "web_extract", "delegate_task", "fan_out_research"} | SKILLS,
}
BLOCKED_MESSAGE = "This tool is not allowed for this agent."
CLICK_REQUIRED_MESSAGE = ("Nothing was sent: this request carries owner_confirmation but Dona Maria has not chosen "
                          "Confirmar in a clarify prompt for it. Ask her with clarify first.")
ONE_DECISION_MESSAGE = ("Nothing was asked: this confirmation carries more than one purchase, and a Confirmar "
                        "authorises one write. Ask for uma compra por vez, so Dona Maria sees exactly what she is "
                        "approving.")
_PACKAGE_PRICE = re.compile(r"(?:pacote|pote|caixinha|lata|vidro|sach[êe]|unidade|barra|ma[çc]o|garrafa)[^?]{0,60}?R\$\s*\d")
REPEATED_QUESTION_MESSAGE = ("Nothing was asked: Dona Maria already answered Cancelar to this very question. Asking it "
                             "again is not a new chance — act on the no, or ask her something different.")
# She answered, and the answer was no: repeating the question is what turns a decision into a loop (full run 01/1).
REFUSED_MESSAGE = ("Nothing was sent: Dona Maria chose Cancelar in the last clarify. That is her decision, not a "
                   "failure — never tell her the system is broken. Do not ask the same thing again: act on the no "
                   "(another dish, the ingredient out of the recipe) or ask her what she wants to do instead.")
_CONFIRMAR = re.compile(r"^Confirmar(?: \(Recommended\))?$")


def decide(role: str, tool_name: str) -> dict | None:
    return None if tool_name in ALLOWED.get(role, set()) else {"action": "block", "message": BLOCKED_MESSAGE}


def _answers(result) -> list[str]:
    try:
        data = json.loads(result) if isinstance(result, str) else result
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("responses"), list):
        return [str(entry.get("user_response", "")) for entry in data["responses"] if isinstance(entry, dict)]
    return [str(data.get("user_response", ""))]


NOT_SENT_ERRORS = {"invalid_request", "missing_token"}  # kitchen_a2a errors raised before the request leaves orchestrator


class ClickLedger:
    """Unused Confirmar answers per orchestrator session; a new clarify replaces whatever was left from the previous one."""

    def __init__(self):
        self._clicks: dict[str, int] = {}
        self._refused: dict[str, bool] = {}
        self._refused_questions: dict[str, set[str]] = {}  # questions she already said no to, per session
        self._lock = threading.Lock()

    def record_clarify(self, session_id: str, result) -> None:
        answers = [answer.strip() for answer in _answers(result)]
        for question, answer in _questions_and_answers(result):
            if answer.lower().startswith("cancelar"):
                self._refused_questions.setdefault(session_id, set()).add(_normalize_question(question))
        with self._lock:
            self._clicks[session_id] = sum(1 for answer in answers if _CONFIRMAR.match(answer))
            self._refused[session_id] = bool(answers) and not self._clicks[session_id] and any(
                answer.lower().startswith("cancelar") for answer in answers)

    def refund(self, session_id: str) -> None:
        with self._lock:
            self._clicks[session_id] = self._clicks.get(session_id, 0) + 1

    def already_refused_question(self, session_id: str, question: str) -> bool:
        with self._lock:
            return _normalize_question(question) in self._refused_questions.get(session_id, set())

    def refused(self, session_id: str) -> bool:
        """Her last clarify was answered Cancelar and nothing else."""
        with self._lock:
            return self._refused.get(session_id, False)

    def consume(self, session_id: str) -> bool:
        with self._lock:
            if self._clicks.get(session_id, 0) <= 0:
                return False
            self._clicks[session_id] -= 1
            return True


def check_click(ledger: ClickLedger, session_id: str, tool_name: str, args: dict | None) -> dict | None:
    if tool_name not in ASK_TOOLS or not (args or {}).get("owner_confirmation"):
        return None
    if ledger.consume(session_id):
        return None
    return {"action": "block", "message": REFUSED_MESSAGE if ledger.refused(session_id) else CLICK_REQUIRED_MESSAGE}


def _normalize_question(question: str) -> str:
    return " ".join((question or "").split()).casefold()


def _questions_and_answers(result):
    """(question, answer) pairs of a clarify result, whatever shape Hermes used for it."""
    try:
        data = json.loads(result) if isinstance(result, str) else result
    except ValueError:
        return []
    if not isinstance(data, dict):
        return []
    responses = data.get("responses")
    if isinstance(responses, list):
        return [(item.get("question", ""), str(item.get("user_response", ""))) for item in responses if isinstance(item, dict)]
    return [(data.get("question", ""), str(data.get("user_response", "")))]


def check_repeat(ledger: ClickLedger, session_id: str, tool_name: str, args: dict | None) -> dict | None:
    """A clarify that asks again, word for word, something she already refused (full run, scenario 03)."""
    if tool_name != "clarify":
        return None
    questions = (args or {}).get("questions")
    asked = [entry.get("question", "") for entry in questions if isinstance(entry, dict)] if isinstance(questions, list) else [(args or {}).get("question", "")]
    if any(question and ledger.already_refused_question(session_id, question) for question in asked):
        return {"action": "block", "message": REPEATED_QUESTION_MESSAGE}
    return None


def check_one_decision(tool_name: str, args: dict | None) -> dict | None:
    """A click-required confirmation that bundles two purchases: one Confirmar authorises one write (D14), so the
    second one comes back as another question anyway (owner's live session)."""
    if tool_name != "clarify":
        return None
    for entry in (args or {}).get("questions") or []:
        if not isinstance(entry, dict):
            continue
        choices = [str(choice).strip() for choice in entry.get("choices") or []]
        if not any(_CONFIRMAR.match(choice) for choice in choices):
            continue
        if len(_PACKAGE_PRICE.findall(entry.get("question") or "")) > 1:
            return {"action": "block", "message": ONE_DECISION_MESSAGE}
    return None
