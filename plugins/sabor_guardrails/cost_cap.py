"""Per-turn cost cap aggregated across agents without a shared store (D37).

fifi starts each owner turn with SABOR_TURN_COST_CAP_USD and sends what is left in trace.turn_cost_remaining_usd;
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

    def breakdown(self, trace_id: str) -> dict[str, str]:
        with self._lock:
            turn = self._turn(trace_id)
            return {self.agent: str(turn["own"]), **{agent: str(usd) for agent, usd in turn["reported"].items()}}
