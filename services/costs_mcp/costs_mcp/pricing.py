"""Pure money math (CLAUDE.md pricing rules). Decimal only, never rounds: rounding is presentation."""

from decimal import Decimal


def unit_cost(total_price_paid: Decimal, quantity_purchased_base: Decimal) -> Decimal:
    """Cost of one base unit (g, ml or unit) = total price paid / quantity purchased."""
    if quantity_purchased_base <= 0:
        raise ValueError(f"quantity_purchased_base must be > 0, got {quantity_purchased_base}")
    return total_price_paid / quantity_purchased_base


def recipe_cmv(lines: list[tuple[Decimal, Decimal]]) -> Decimal:
    """CMV of a recipe = sum of quantity_used_base x unit_cost over its (quantity, unit_cost) lines."""
    return sum((quantity * cost for quantity, cost in lines), Decimal(0))


def min_price(cmv: Decimal, fee_rate: Decimal) -> Decimal:
    """Lowest price that does not lose money after the platform fee: P >= CMV / (1 - fee)."""
    if not Decimal(0) <= fee_rate < Decimal(1):
        raise ValueError(f"fee_rate must be in [0, 1), got {fee_rate}")
    return cmv / (Decimal(1) - fee_rate)
