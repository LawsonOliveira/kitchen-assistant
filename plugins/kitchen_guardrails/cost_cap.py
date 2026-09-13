"""Per-turn cost cap aggregated across agents without a shared store (D37).

orchestrator starts each owner turn with KITCHEN_TURN_COST_CAP_USD and sends what is left in trace.turn_cost_remaining_usd;
each expert starts the same trace with that remainder. Every agent adds its own spend (tokens × price table) and
the cost_usd_spent each A2A reply reports, and blocks its next model call once nothing is left.
"""

import threading
from decimal import Decimal

_MILLION = Decimal(1_000_000)


def cost_of_call(model: str, tokens_in: int, tokens_out: int, prices: dict) -> Decimal:
    """USD for one model call; prices = {model: (input USD per million tokens, output USD per million tokens)}."""
    if model not in prices:
        raise ValueError(f"no price for model {model!r}: the cost cap cannot account for this call")
    input_rate, output_rate = (Decimal(str(rate)) for rate in prices[model])
    return (Decimal(tokens_in) * input_rate + Decimal(tokens_out) * output_rate) / _MILLION


class CostCap:
    def __init__(self, cap_usd: Decimal, agent: str):
        self.cap, self.agent = Decimal(cap_usd), agent
        self._turns: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self, trace_id: str, received_remaining: Decimal | None = None) -> None:
        limit = self.cap if received_remaining is None else min(self.cap, Decimal(received_remaining))
        with self._lock:
            self._turns[trace_id] = {"limit": limit, "own": Decimal(0), "reported": {}}

    def _turn(self, trace_id: str) -> dict:
        return self._turns.setdefault(trace_id, {"limit": self.cap, "own": Decimal(0), "reported": {}})

    def add_own(self, trace_id: str, usd: Decimal) -> None:
        with self._lock:
            self._turn(trace_id)["own"] += Decimal(usd)

    def add_reported(self, trace_id: str, usd: Decimal, agent: str) -> None:
        with self._lock:
            reported = self._turn(trace_id)["reported"]
            reported[agent] = reported.get(agent, Decimal(0)) + Decimal(usd)

    def remaining(self, trace_id: str) -> Decimal:
        with self._lock:
            turn = self._turn(trace_id)
            return turn["limit"] - turn["own"] - sum(turn["reported"].values(), Decimal(0))

    def allows_next_call(self, trace_id: str) -> bool:
        return self.remaining(trace_id) > 0

    def spent(self, trace_id: str) -> Decimal:
        with self._lock:
            return self._turn(trace_id)["own"]

    def breakdown(self, trace_id: str) -> dict[str, str]:
        with self._lock:
            turn = self._turn(trace_id)
            return {self.agent: str(turn["own"]), **{agent: str(usd) for agent, usd in turn["reported"].items()}}


class SessionCosts:
    """Hermes sessions → the turn they are spending for: a root session starts one turn per owner message (orchestrator) or
    per A2A request (experts, researcher); delegated children count for their parent's current turn."""

    def __init__(self, cap_usd: Decimal, agent: str):
        self.cap = CostCap(cap_usd, agent)
        self._turn_of: dict[str, str] = {}
        self._parent: dict[str, str] = {}
        self._lock = threading.Lock()

    def begin(self, session_id: str, turn_id: str, received_remaining: Decimal | None = None) -> None:
        key = f"{session_id}:{turn_id}"
        with self._lock:
            self._turn_of[session_id] = key
        self.cap.start(key, received_remaining)

    def link_child(self, child_session_id: str, parent_session_id: str) -> None:
        with self._lock:
            self._parent[child_session_id] = parent_session_id

    def _trace(self, session_id: str) -> str:
        with self._lock:
            seen = set()
            while session_id in self._parent and session_id not in seen:
                seen.add(session_id)
                session_id = self._parent[session_id]
            return self._turn_of.get(session_id, session_id)

    def add_own(self, session_id: str, usd: Decimal) -> None:
        self.cap.add_own(self._trace(session_id), usd)

    def add_reported(self, session_id: str, usd: Decimal, agent: str) -> None:
        self.cap.add_reported(self._trace(session_id), usd, agent)

    def spent(self, session_id: str) -> Decimal:
        return self.cap.spent(self._trace(session_id))

    def remaining(self, session_id: str) -> Decimal:
        return self.cap.remaining(self._trace(session_id))

    def allows_next_call(self, session_id: str) -> bool:
        return self.cap.allows_next_call(self._trace(session_id))

    def breakdown(self, session_id: str) -> dict[str, str]:
        return self.cap.breakdown(self._trace(session_id))


# Anthropic first-party USD per million tokens (input, output), 2026-09 (plugins/kitchen_guardrails/NOTES.md §3).
PRICES = {"claude-sonnet-5": ("2.00", "10.00"), "claude-haiku-4-5-20251001": ("1.00", "5.00")}
