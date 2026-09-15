"""What is still open in the journey, read from the results that pass through the session (full run, scenario 05).

Dona Sálvia's contract says the closing line ends with the next question; it held two turns out of three, and the turn
that did not ended the conversation with a dish registered and never accepted. So the code checks it: while something
is open and her reply asks nothing, the turn goes back to her once, naming what is missing.
"""

import threading

from .grounding import _walk

ACCEPT = "o prato registrado ainda não foi aceito"
PRICE = "o prato aceito ainda não tem preço"


class Pending:
    """Dish state per session: candidate -> accepted -> priced."""

    def __init__(self):
        self._state: dict[str, str] = {}
        self._lock = threading.Lock()

    def read_tool_result(self, session_id: str, result) -> None:
        status, priced = None, False
        for key, value in _walk(result):
            if key == "status" and value in ("candidate", "accepted", "rejected"):
                status = value
            if key in ("display_price", "selected_price_display"):
                priced = True
        with self._lock:
            if priced:
                self._state[session_id] = "done"
            elif status == "candidate":
                self._state[session_id] = "candidate"
            elif status == "accepted":
                self._state[session_id] = "accepted"
            elif status == "rejected" and self._state.get(session_id) == "candidate":
                self._state.pop(session_id, None)

    def open_for(self, session_id: str) -> str | None:
        with self._lock:
            state = self._state.get(session_id)
        return ACCEPT if state == "candidate" else PRICE if state == "accepted" else None


def continue_message(state: Pending, session_id: str, final_response: str, attempt: int) -> str | None:
    """The turn goes back to her once, when she closed without a question and something is still open."""
    if attempt or "?" in (final_response or ""):
        return None
    missing = state.open_for(session_id)
    if not missing:
        return None
    return (f"Sua resposta terminou sem pergunta e {missing}. Feche com a próxima pergunta para Dona Maria — "
            "ela não tem o que responder e a conversa morre aí.")
