"""Bridge to kitchen_guardrails' per-turn cost accounting (D37): what is left of the owner turn and what this agent spent.

Hermes chooses the module names of loaded plugins, so the accounting object is found by suffix; without the
guardrails plugin (unit tests) nothing is tracked and the configured cap is sent.
"""

import os
import sys


def _session_costs():
    module = next((module for name, module in list(sys.modules.items()) if name.endswith("kitchen_guardrails.cost_cap")), None)
    return getattr(module, "ACTIVE", None)


def spent_usd(session_id: str) -> float:
    costs = _session_costs()
    return float(costs.spent(session_id)) if costs else 0.0


def remaining_usd(session_id: str) -> float:
    costs = _session_costs()
    if costs is None:
        return float(os.environ.get("KITCHEN_TURN_COST_CAP_USD", "5.00"))
    return max(0.0, float(costs.remaining(session_id)))
