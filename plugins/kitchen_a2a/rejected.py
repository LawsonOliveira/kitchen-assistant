"""Dishes Dona Maria refused, per session (full run, scenario 09): the ledger already refuses to register a rejected
name again, and this keeps the research call from spending a web search on it — whatever the model remembers."""

import json
import threading

RESEARCH_TASK = "suggest_dishes"


class RejectedDishes:
    def __init__(self):
        self._names: dict[str, dict[int, str]] = {}  # session -> dish_id -> name
        self._rejected: dict[str, list[str]] = {}
        self._lock = threading.Lock()

    def remember_candidate(self, session_id: str, request: dict, reply) -> None:
        """The dish_id the expert answered with, tied to the name the request carried."""
        if (request or {}).get("task") != "register_candidate":
            return
        name = (((request.get("payload") or {}).get("recipe")) or {}).get("name")
        dish_id = (((_parsed(reply) or {}).get("result") or {}).get("dish") or {}).get("dish_id")
        if name and isinstance(dish_id, int):
            with self._lock:
                self._names.setdefault(session_id, {})[dish_id] = name

    def remember_rejection(self, session_id: str, request: dict) -> None:
        if (request or {}).get("task") != "reject_candidate":
            return
        dish_id = (request.get("payload") or {}).get("dish_id")
        with self._lock:
            name = self._names.get(session_id, {}).get(dish_id)
            if name and name not in self._rejected.setdefault(session_id, []):
                self._rejected[session_id].append(name)

    def names(self, session_id: str) -> list[str]:
        with self._lock:
            return list(self._rejected.get(session_id, []))

    def exclude_in(self, session_id: str, request: dict) -> None:
        """Add every refused name to a suggest_dishes request, keeping the ones the model already listed."""
        if (request or {}).get("task") != RESEARCH_TASK:
            return
        payload = request.setdefault("payload", {})
        listed = payload.get("exclude_dish_names") or []
        payload["exclude_dish_names"] = listed + [name for name in self.names(session_id) if name not in listed]


def _parsed(reply):
    try:
        return json.loads(reply) if isinstance(reply, str) else reply
    except ValueError:
        return None
