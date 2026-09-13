"""Per-agent tool allowlists in pre_tool_call (D13) and the deterministic click check (open question 10).

pre_tool_call is the only Hermes hook that fails closed, so the allowlist lives there on all five agents. On fifi,
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
    return {f"mcp__costs__{tool}" for tool in tools}


ALLOWED = {
    "fifi": {"clarify", "memory"} | ASK_TOOLS | SKILLS | _mcp(*READ),
    "recipe_expert": {"research"} | SKILLS | _mcp(*READ, "check_viability", "register_candidate_dish", "reject_candidate_dish", "set_launch_batch_portions",
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


NOT_SENT_ERRORS = {"invalid_request", "missing_token"}  # sabor_a2a errors raised before the request leaves fifi


class ClickLedger:
    """Unused Confirmar answers per fifi session; a new clarify replaces whatever was left from the previous one."""

    def __init__(self):
        self._clicks: dict[str, int] = {}
        self._lock = threading.Lock()

    def record_clarify(self, session_id: str, result) -> None:
        with self._lock:
            self._clicks[session_id] = sum(1 for answer in _answers(result) if _CONFIRMAR.match(answer.strip()))

    def refund(self, session_id: str) -> None:
        with self._lock:
            self._clicks[session_id] = self._clicks.get(session_id, 0) + 1

    def consume(self, session_id: str) -> bool:
        with self._lock:
            if self._clicks.get(session_id, 0) <= 0:
                return False
            self._clicks[session_id] -= 1
            return True


def check_click(ledger: ClickLedger, session_id: str, tool_name: str, args: dict | None) -> dict | None:
    if tool_name not in ASK_TOOLS or not (args or {}).get("owner_confirmation"):
        return None
    return None if ledger.consume(session_id) else {"action": "block", "message": CLICK_REQUIRED_MESSAGE}
