"""What Dona Maria is about to approve, put in the question itself (owner's live session).

She was asked to accept a dish whose recipe had never been shown, and to save a menu text she had never read. Both
travel through the guard: the recipe in the register_candidate request, the copy in the marketing reply. So the
question carries them, instead of trusting the model to remember to show them.
"""

import json
import threading

ACCEPT_WORDS = ("aceitar", "aceito", "aceite")
SAVE_WORDS = ("salvar", "descrição", "descricao", "cardápio do", "cardapio do")


class Approvals:
    def __init__(self):
        self._recipes: dict[str, dict] = {}
        self._copies: dict[str, dict] = {}
        self._lock = threading.Lock()

    def remember_request(self, session_id: str, request) -> None:
        recipe = ((request or {}).get("payload") or {}).get("recipe")
        if isinstance(recipe, dict) and recipe.get("ingredients"):
            with self._lock:
                self._recipes[session_id] = recipe

    def remember_result(self, session_id: str, result) -> None:
        copy = (((_parsed(result) or {}).get("result") or {}).get("menu_copy"))
        if isinstance(copy, dict) and copy.get("title"):
            with self._lock:
                self._copies[session_id] = copy

    def with_evidence(self, session_id: str, question: str) -> str:
        lowered = (question or "").lower()
        with self._lock:
            recipe, copy = self._recipes.get(session_id), self._copies.get(session_id)
        if copy and any(word in lowered for word in SAVE_WORDS) and copy["title"].lower() not in lowered:
            return f'{question}\n\nTítulo: {copy["title"]}\nDescrição: {copy.get("description", "")}'
        if recipe and any(word in lowered for word in ACCEPT_WORDS) and "ingrediente" not in lowered:
            lines = ", ".join(f'{item["name"]} {_plain(item.get("quantity"))} {item.get("unit", "")}'.strip()
                              for item in recipe["ingredients"])
            return f'{question}\n\n{recipe["name"]} rende {recipe.get("yield_portions", "?")} porções: {lines}'
        return question


def _plain(value) -> str:
    text = f"{value}"
    return text[:-2] if text.endswith(".0") else text


def _parsed(value):
    try:
        return json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return None
