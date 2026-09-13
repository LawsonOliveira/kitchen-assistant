"""Household measures -> base units (PLAN.md D23).

A fixed, ingredient-specific table instead of LLM guesses (models state densities confidently and wrongly).
Table values are estimates; a factor the owner told us always wins. Anything else fails loud and becomes a
question for the owner.
"""

from decimal import Decimal

# (measure, pantry ingredient name or None for "any ingredient") -> (amount per measure, base unit)
HOUSEHOLD_MEASURES = {
    ("cup", "Farinha de trigo"): (Decimal("120"), "g"),
    ("cup", "Arroz branco tipo 1"): (Decimal("185"), "g"),
    ("cup", "Açúcar"): (Decimal("180"), "g"),
    ("cup", "Leite integral"): (Decimal("240"), "ml"),
    ("tablespoon", "Manteiga"): (Decimal("15"), "g"),
    ("tablespoon", "Óleo de soja"): (Decimal("15"), "ml"),
    ("tablespoon", None): (Decimal("15"), "ml"),
    ("teaspoon", None): (Decimal("5"), "ml"),
    ("clove", "Alho"): (Decimal("5"), "g"),
    ("pinch", None): (Decimal("1"), "g"),
    ("drizzle", None): (Decimal("5"), "ml"),
    ("to_taste", None): (Decimal("1"), "g"),
    ("can", "Creme de leite"): (Decimal("200"), "g"),
    ("can", "Leite condensado"): (Decimal("395"), "g"),
    ("can", "Milho verde"): (Decimal("170"), "g"),
    ("can", "Extrato de tomate"): (Decimal("340"), "g"),
}


class MissingConversionError(ValueError):
    def __init__(self, ingredient: str, measure: str):
        super().__init__(f"no conversion for {measure!r} of {ingredient!r}; ask the owner")
        self.ingredient = ingredient
        self.measure = measure


def resolve_measure(ingredient_name: str, measure: str, count: Decimal,
                    owner_factors: dict | None = None) -> tuple[Decimal, str, bool]:
    """(quantity in base unit, base unit, is_estimate). owner_factors: {(ingredient, measure): (amount, base unit)}."""
    if owner_factors and (ingredient_name, measure) in owner_factors:
        amount, base_unit = owner_factors[(ingredient_name, measure)]
        return count * amount, base_unit, False
    entry = HOUSEHOLD_MEASURES.get((measure, ingredient_name)) or HOUSEHOLD_MEASURES.get((measure, None))
    if entry is None:
        raise MissingConversionError(ingredient_name, measure)
    amount, base_unit = entry
    return count * amount, base_unit, True
