"""What Dona Maria is about to approve, put in the question itself (owner's live session).

She was asked to accept a dish whose recipe had never been shown, and to save a menu text she had never read. Both
travel through the guard: the recipe in the register_candidate request, the copy in the marketing reply. So the
question carries them, instead of trusting the model to remember to show them.
"""

import json
import threading
from decimal import Decimal, InvalidOperation

ACCEPT_WORDS = ("aceitar", "aceito", "aceite")
METHOD_CHOICE = "Ver a receita completa"
# The recipe contract keeps the source page, never the steps (D5), so the choice hands her the page itself.
PLURALS = ("dente", "unidade", "colher", "xícara", "fatia", "lata", "pacote", "ramo", "folha", "pitada", "caixinha",
           "colher de sopa", "colher de chá")
# The contract writes the units in English (contracts/recipe.schema.json); she reads them in her own.
UNITS = {"g": "g", "kg": "kg", "ml": "ml", "l": "L", "unit": "unidade", "cup": "xícara", "tablespoon": "colher de sopa",
         "teaspoon": "colher de chá", "clove": "dente", "pinch": "pitada", "can": "lata", "package": "pacote"}
NO_QUANTITY = {"to_taste": "a gosto", "drizzle": "um fio"}
SAVE_WORDS = ("salvar", "descrição", "descricao", "cardápio do", "cardapio do")


class Approvals:
    def __init__(self):
        self._recipes: dict[str, dict] = {}
        self._copies: dict[str, dict] = {}
        self._candidates: dict[str, dict] = {}
        self._lock = threading.Lock()

    def remember_request(self, session_id: str, request) -> None:
        payload = (request or {}).get("payload") or {}
        recipe = payload.get("recipe")
        if isinstance(recipe, dict) and recipe.get("ingredients"):
            with self._lock:
                self._recipes[session_id] = {**recipe, "launch_batch_portions": payload.get("launch_batch_portions")}

    def remember_result(self, session_id: str, result) -> None:
        answer = (_parsed(result) or {}).get("result") or {}
        copy = answer.get("menu_copy")
        if isinstance(copy, dict) and copy.get("title"):
            with self._lock:
                self._copies[session_id] = copy
        for candidate in answer.get("candidates") or []:
            name = ((candidate or {}).get("recipe") or {}).get("name")
            if name:
                with self._lock:
                    self._candidates.setdefault(session_id, {})[name] = candidate

    def with_evidence(self, session_id: str, question: str) -> str:
        lowered = (question or "").lower()
        with self._lock:
            recipe, copy = self._recipes.get(session_id), self._copies.get(session_id)
        if copy and any(word in lowered for word in SAVE_WORDS) and copy["title"].lower() not in lowered:
            return f'{question}\n\nTítulo: {copy["title"]}\nDescrição: {copy.get("description", "")}'
        if recipe and any(word in lowered for word in ACCEPT_WORDS) and "ingrediente" not in lowered:
            # She reads the batch she will actually cook, never the recipe's own yield (owner, 2026-09-16): a recipe for
            # 8 shown to someone cooking 6 makes her buy the wrong amount of everything.
            batch, factor = _batch(recipe)
            lines = "\n".join(f'- {item["name"]}: {_amount(item.get("quantity"), item.get("unit", ""), factor)}'
                              for item in recipe["ingredients"])
            head = f'{recipe["name"]}, lote de {batch} porções' if recipe.get("launch_batch_portions") \
                else f'{recipe["name"]} rende {batch} porções'
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
            question = self._with_pantry(session_id, question, choices)
            if question != entry.get("question") and any(word in question.lower() for word in ACCEPT_WORDS) \
                    and self._recipe_url(session_id) and METHOD_CHOICE not in choices:
                choices = choices + [METHOD_CHOICE]
            rewritten.append({**entry, "question": question, **({"choices": choices} if choices else {})})
        return {**args, "questions": rewritten} if rewritten != questions else args

    def _with_pantry(self, session_id: str, question: str, choices: list) -> str:
        """The question that offers her the dishes, with what each one costs her in shopping (owner, 2026-09-16)."""
        with self._lock:
            known = dict(self._candidates.get(session_id) or {})
        offered = [candidate for name, candidate in known.items() if _offered(name, choices)]
        if not offered or "% da despensa" in question:
            return question
        return f"{question.rstrip()}\n\n" + "\n".join(_pantry_line(candidate) for candidate in offered)

    def _recipe_url(self, session_id: str) -> str:
        with self._lock:
            return (self._recipes.get(session_id) or {}).get("source_url", "")

    def method_url(self, session_id: str) -> str:
        return self._recipe_url(session_id)


def _offered(name: str, choices: list) -> bool:
    """The choices are the model's words: "Lasanha" is the dish the expert called "Lasanha de carne moída"."""
    dish = name.casefold()
    return any(dish == choice or dish.startswith(choice) or choice.startswith(dish)
               for choice in (str(item).casefold() for item in choices))


def _pantry_line(candidate: dict) -> str:
    """"Lasanha de carne moída: 69% da despensa. Falta comprar: massa de lasanha, creme de leite."""
    name = (candidate.get("recipe") or {}).get("name", "")
    coverage = candidate.get("pantry_coverage_pct")
    missing = [item for item in candidate.get("missing_ingredients") or [] if item]
    head = f"{name}: {coverage}% da despensa." if isinstance(coverage, int) else f"{name}:"
    return f"{head} Falta comprar: {', '.join(missing)}." if missing else f"{head} Não falta nada."


def _batch(recipe: dict) -> tuple:
    """The batch she will cook and how much of each ingredient that is, as a fraction of the recipe's own yield."""
    yield_portions, batch = recipe.get("yield_portions"), recipe.get("launch_batch_portions")
    if not batch:
        return yield_portions if yield_portions else "?", Decimal(1)
    try:
        return batch, Decimal(str(batch)) / Decimal(str(yield_portions))
    except (InvalidOperation, ZeroDivisionError, TypeError):
        return batch, Decimal(1)  # whatever the model wrote, the list she reads is worth more than the scaling


def _amount(quantity, unit: str, factor: Decimal = Decimal(1)) -> str:
    """Her own way of writing it: 1,5 kg, 3 dentes and "a gosto", never 1.5 kg, 3 clove or None to_taste."""
    if unit in NO_QUANTITY or quantity is None:
        return NO_QUANTITY.get(unit, "a gosto")
    label = UNITS.get(unit, unit)
    text = _number(quantity, factor)
    plural = _plural(label) if label in PLURALS and text not in ("1", "0,5") else label
    return f"{text} {plural}".strip()


def _plural(label: str) -> str:
    """"colher de sopa" pluralises the spoon, not the soup."""
    head, _, tail = label.partition(" ")
    return f"{head}es {tail}".strip() if head.endswith("r") else f"{head}s {tail}".strip()


def _number(quantity, factor: Decimal) -> str:
    try:
        value = Decimal(str(quantity)) * factor
    except (InvalidOperation, TypeError):
        return f"{quantity}".removesuffix(".0").replace(".", ",")
    if value != value.to_integral_value():
        value = value.quantize(Decimal("0.001"))
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", ",")


def _parsed(value):
    try:
        return json.loads(value) if isinstance(value, str) else value
    except ValueError:
        return None
