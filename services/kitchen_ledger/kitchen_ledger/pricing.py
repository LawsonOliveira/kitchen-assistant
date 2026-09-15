"""Pure money math (CLAUDE.md pricing rules). Decimal only; rounding happens only in the format_* helpers."""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
NINETY_CENTS = Decimal("0.90")
DEFAULT_TARGETS = (Decimal("0.35"), Decimal("0.30"), Decimal("0.25"))


def unit_cost(total_price_paid: Decimal, quantity_purchased_base: Decimal) -> Decimal:
    """Cost of one base unit (g, ml or unit) = total price paid / quantity purchased."""
    if quantity_purchased_base <= 0:
        raise ValueError(f"quantity_purchased_base must be > 0, got {quantity_purchased_base}")
    return total_price_paid / quantity_purchased_base


def recipe_cmv(lines: list[tuple[Decimal, Decimal]]) -> Decimal:
    """CMV of a recipe = sum of quantity_used_base x unit_cost over its (quantity, unit_cost) lines."""
    return sum((quantity * cost for quantity, cost in lines), Decimal(0))


def cmv_per_portion(recipe_cmv_value: Decimal, yield_portions: int) -> Decimal:
    """Delivery sells portions, so the CMV that prices a dish is per portion."""
    if yield_portions <= 0:
        raise ValueError(f"yield_portions must be > 0, got {yield_portions}")
    return recipe_cmv_value / Decimal(yield_portions)


def min_price(cmv: Decimal, fee_rate: Decimal) -> Decimal:
    """Lowest price that does not lose money after the platform fee: P >= CMV / (1 - fee)."""
    if not Decimal(0) <= fee_rate < Decimal(1):
        raise ValueError(f"fee_rate must be in [0, 1), got {fee_rate}")
    return cmv / (Decimal(1) - fee_rate)


def min_price_with_packaging(cmv: Decimal, packaging_unit_cost: Decimal, fee_rate: Decimal) -> Decimal:
    """The brief's minimum ignores packaging; this one shows when packaging turns a sale into a loss (D22)."""
    return min_price(cmv + packaging_unit_cost, fee_rate)


def round_up_commercial(price: Decimal) -> Decimal:
    """Smallest x,90 >= price: commercial ending that never goes below the computed price."""
    return (price - NINETY_CENTS).to_integral_value(rounding=ROUND_CEILING) + NINETY_CENTS


@dataclass(frozen=True)
class Scenario:
    target_cmv_pct: Decimal
    raw_price: Decimal
    display_price: Decimal
    owner_receives: Decimal
    profit: Decimal
    profit_after_packaging: Decimal | None
    margin_on_sale: Decimal
    below_min: bool


def price_scenarios(cmv: Decimal, packaging_unit_cost: Decimal | None, fee_rate: Decimal,
                    targets: tuple[Decimal, ...] = DEFAULT_TARGETS) -> list[Scenario]:
    """One scenario per target CMV% of the price (food-service vocabulary, comparable across dishes — D20)."""
    minimum = min_price(cmv, fee_rate)
    scenarios = []
    for target in targets:
        raw_price = cmv / target
        display_price = round_up_commercial(raw_price)
        owner_receives = display_price * (Decimal(1) - fee_rate)
        profit = owner_receives - cmv
        scenarios.append(Scenario(
            target_cmv_pct=target,
            raw_price=raw_price,
            display_price=display_price,
            owner_receives=owner_receives,
            profit=profit,
            profit_after_packaging=None if packaging_unit_cost is None else profit - packaging_unit_cost,
            margin_on_sale=profit / display_price,
            below_min=display_price < minimum,
        ))
    return scenarios


def format_brl(value: Decimal) -> str:
    """Presentation only: half-up to the cent, Brazilian separators."""
    text = f"{value.quantize(CENT, rounding=ROUND_HALF_UP):,.2f}"
    return "R$ " + text.replace(",", "_").replace(".", ",").replace("_", ".")


def format_brl_min(value: Decimal) -> str:
    """Minimum prices round UP: half-up could show a minimum that loses money (e.g. 3.5733 -> 3,57)."""
    return format_brl(value.quantize(CENT, rounding=ROUND_CEILING))


_PER_UNIT = {"g": (Decimal(1000), "kg"), "ml": (Decimal(1000), "L"), "unit": (Decimal(1), "un")}


def format_unit_cost(total_price_paid: Decimal, quantity_purchased_base: Decimal, base_unit: str) -> str:
    """Unit cost shown per kg, L or un — per gram would be unreadable (R$ 0,00498)."""
    factor, label = _PER_UNIT[base_unit]
    return f"{format_brl(unit_cost(total_price_paid, quantity_purchased_base) * factor)}/{label}"


def _pct(rate: Decimal) -> str:
    """"10%", not "10.00%": she reads it out loud."""
    return f"{(rate * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP)}%"


def price_chain_display(total_price_paid: Decimal, quantity_purchased_base: Decimal, base_unit: str) -> str:
    """What a package costs per kilo, litre or unit, with the division she can redo (probes: package prices had none)."""
    quantity = quantity_purchased_base
    shown = quantity.quantize(Decimal(1)) if quantity == quantity.to_integral_value() else quantity.normalize()
    return (f"{format_brl(total_price_paid)} ÷ {shown} {base_unit} = "
            f"{format_unit_cost(total_price_paid, quantity_purchased_base, base_unit)}")


def cost_chain_display(recipe_cmv_value: Decimal, yield_portions: int, per_portion: Decimal) -> str:
    """The account of the cost per portion, as Dona Maria would redo it (probes A and B)."""
    return f"{format_brl(recipe_cmv_value)} ÷ {yield_portions} porções = {format_brl(per_portion)} por porção"


def min_price_chain_display(per_portion: Decimal, fee_rate: Decimal) -> str:
    keep = (Decimal(1) - fee_rate).quantize(Decimal("0.01"))
    return (f"{format_brl(per_portion)} ÷ {str(keep).replace('.', ',')} = {format_brl_min(min_price(per_portion, fee_rate))}, "
            f"porque o iFood fica com {_pct(fee_rate)}")


def profit_chain_display(display_price: Decimal, owner_receives: Decimal, per_portion: Decimal, fee_rate: Decimal) -> str:
    profit = owner_receives - per_portion
    return (f"{format_brl(display_price)} − {_pct(fee_rate)} = {format_brl(owner_receives)}; "
            f"{format_brl(owner_receives)} − {format_brl(per_portion)} = {format_brl(profit)} de lucro por porção")


def promotion_chain_display(price: Decimal, discount_pct: Decimal, promo_price: Decimal, profit: Decimal) -> str:
    return (f"{format_brl(price)} − {_pct(discount_pct)} = {format_brl(promo_price)}, "
            f"lucro {format_brl(profit)} por porção")


@dataclass(frozen=True)
class Alert:
    code: str
    severity: str
    actual_cmv_pct: Decimal
    target_cmv_pct: Decimal
    min_price_display: str


def price_alerts(cmv: Decimal, selected_price: Decimal, selected_target: Decimal, fee_rate: Decimal,
                 packaging_unit_cost: Decimal | None = None) -> list[Alert]:
    """Suggestion-only alerts after a cost change (D28); nothing is repriced automatically."""
    actual = cmv / selected_price
    minimum = min_price(cmv, fee_rate)
    alerts = []
    if selected_price < minimum:
        alerts.append(Alert("below_min", "critical", actual, selected_target, format_brl_min(minimum)))
    if packaging_unit_cost is not None:
        with_packaging = min_price_with_packaging(cmv, packaging_unit_cost, fee_rate)
        if selected_price < with_packaging:
            alerts.append(Alert("below_min_with_packaging", "critical", actual, selected_target, format_brl_min(with_packaging)))
    if actual > selected_target:
        alerts.append(Alert("cmv_pct_above_target", "warning", actual, selected_target, format_brl_min(minimum)))
    return alerts
