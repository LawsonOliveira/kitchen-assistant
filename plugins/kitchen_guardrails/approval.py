"""What Dona Maria is about to approve, put in the question itself (owner's live session).

She was asked to accept a dish whose recipe had never been shown, and to save a menu text she had never read. Both
travel through the guard: the recipe in the register_candidate request, the copy in the marketing reply. So the
question carries them, instead of trusting the model to remember to show them.
"""

import json
import threading

ACCEPT_WORDS = ("aceitar", "aceito", "aceite")
METHOD_CHOICE = "Ver o modo de preparo"
# The recipe contract keeps the source page, never the steps, so the method is fetched from the page when she asks.
PLURALS = ("dente", "unidade", "colher", "xícara", "fatia", "lata", "pacote", "ramo", "folha", "pitada", "caixinha")
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
            lines = "\n".join(f'- {item["name"]}: {_amount(item.get("quantity"), item.get("unit", ""))}'
                              for item in recipe["ingredients"])
            head = f'{recipe["name"]} rende {recipe.get("yield_portions", "?")} porções'
            if recipe.get("prep_time_minutes"):
                head += f' em {recipe["prep_time_minutes"]} min'
            return f"{question}\n\n{head}:\n{lines}"
        return question

    def clarify_with_evidence(self, session_id: str, args: dict) -> dict:
        """The clarify arguments with the evidence in each question, and the method offered on the accept question."""
        questions = (args or {}).get("questions")
        if not isinstance(questions, list):
            return args
        rewritten = []
        for entry in questions:
            if not isinstance(entry, dict):
                rewritten.append(entry)
                continue
            question = self.with_evidence(session_id, entry.get("question", ""))
            choices = list(entry.get("choices") or [])
            if question != entry.get("question") and any(word in question.lower() for word in ACCEPT_WORDS) \
                    and self._recipe_url(session_id) and METHOD_CHOICE not in choices:
                choices = choices + [METHOD_CHOICE]
            rewritten.append({**entry, "question": question, **({"choices": choices} if choices else {})})
        return {**args, "questions": rewritten} if rewritten != questions else args

    def _recipe_url(self, session_id: str) -> str:
        with self._lock:
            return (self._recipes.get(session_id) or {}).get("source_url", "")

    def method_url(self, session_id: str) -> str:
        return self._recipe_url(session_id)


def _amount(quantity, unit: str) -> str:
    """Her own way of writing it: 1,5 kg and 3 dentes, not 1.5 kg and 3 dente."""
    text = f"{quantity}"
    if text.endswith(".0"):
        text = text[:-2]
    text = text.replace(".", ",")
    plural = f"{unit}s" if unit in PLURALS and quantity not in (1, "1") else unit
    return f"{text} {plural}".strip()


def _parsed(value):
    try:
        return json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return None
