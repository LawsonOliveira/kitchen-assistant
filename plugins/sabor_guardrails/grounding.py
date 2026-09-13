"""Deterministic R$ grounding (D12): every amount in Dona Fifi's answer must be a display string an expert returned."""

import json
import re

_BRL = re.compile(r"R\$\s*(\d{1,3}(?:\.\d{3})*,\d{2})(/(?:kg|L|un))?")
BUDGET_DISPLAY = "R$ 80,00"  # the brief's starting budget, stated before any tool runs


def extract_brl(text: str) -> set[str]:
    """Money amounts as normalized display strings ("R$ 1.234,56", "R$ 4,98/kg")."""
    return {f"R$ {amount}{suffix or ''}" for amount, suffix in _BRL.findall((text or "").replace(" ", " "))}


def _amount(display: str) -> str:
    return display.split("/", 1)[0]


class SessionGrounding:
    """Money display strings seen in the session's expert and MCP results, plus the initial budget."""

    def __init__(self):
        self.amounts = {_amount(BUDGET_DISPLAY)}

    def add_from_tool_result(self, result) -> None:
        for key, value in _walk(result):
            if "display" in key and isinstance(value, str):  # *_display fields and scenario display_price
                self.amounts |= {_amount(display) for display in extract_brl(value)}

    def ungrounded(self, text: str) -> set[str]:
        return {display for display in extract_brl(text) if _amount(display) not in self.amounts}


def _walk(value, key: str = ""):
    """(key, value) pairs of every nested field; JSON text (MCP envelopes, A2A replies) is decoded first."""
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except ValueError:
            yield key, value
            return
        if isinstance(decoded, (dict, list)):
            yield from _walk(decoded, key)
        else:
            yield key, value
    elif isinstance(value, dict):
        for child_key, child in value.items():
            yield from _walk(child, str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child, key)
