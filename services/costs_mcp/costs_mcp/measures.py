"""Household measures -> base units (PLAN.md D23, PL6).

The measures live in the database (the D23 table as seed rows, web estimates recipe_expert found, her confirmations);
resolution never guesses: a factor the owner told us always wins, a web estimate is refused until she confirms it, and
anything else fails loud and becomes a question.
"""

from decimal import Decimal

# Small fixed estimates, in the ingredient's own base unit (g or ml): "óleo a gosto" is 1 ml, never a density question.
SMALL_ESTIMATES = {"to_taste": Decimal("1"), "pinch": Decimal("1"), "drizzle": Decimal("5")}


class MissingConversionError(ValueError):
    def __init__(self, ingredient: str, measure: str):
        super().__init__(f"no conversion for {measure!r} of {ingredient!r}; ask the owner")
        self.ingredient = ingredient
        self.measure = measure


class UnconfirmedMeasureError(MissingConversionError):
    """A measure found on the web: shown to the owner, never used in CMV until she confirms it (PL6, like D27)."""

    def __init__(self, ingredient: str, measure: str, entry: dict):
        super().__init__(ingredient, measure)
        self.amount_display = f"{format(Decimal(entry['amount']).normalize(), 'f')} {entry['unit']}"
        self.source_url = entry.get("source_url")


def resolve_measure(ingredient_name: str, measure: str, count: Decimal, owner_factors: dict | None = None,
                    base_unit: str | None = None, table: dict | None = None) -> tuple[Decimal, str, bool]:
    """(quantity in base unit, base unit, is_estimate). owner_factors: {(ingredient, measure): (amount, base unit)};
    table: {(measure, ingredient or None): {"amount", "unit", "source", "source_url"}} from the measures table;
    base_unit is the ingredient's base unit, which small fixed estimates follow."""
    if owner_factors and (ingredient_name, measure) in owner_factors:
        amount, factor_unit = owner_factors[(ingredient_name, measure)]
        return count * amount, factor_unit, False
    if base_unit is not None and measure in SMALL_ESTIMATES:
        if base_unit not in ("g", "ml"):  # one "unit" can cost R$ 79,90: never estimate whole units
            raise MissingConversionError(ingredient_name, measure)
        return count * SMALL_ESTIMATES[measure], base_unit, True
    table = table or {}
    entry = table.get((measure, ingredient_name)) or table.get((measure, None))
    if entry is None:
        raise MissingConversionError(ingredient_name, measure)
    if entry["source"] == "web_estimate":
        raise UnconfirmedMeasureError(ingredient_name, measure, entry)
    return count * Decimal(entry["amount"]), entry["unit"], entry["source"] != "owner_confirmed"
