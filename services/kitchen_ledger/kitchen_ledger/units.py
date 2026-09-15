"""The only place units are converted (CLAUDE.md). Base units: g, ml, unit."""

import re
from dataclasses import dataclass
from decimal import Decimal

_SIMPLE = {
    "g": ("g", Decimal(1)),
    "kg": ("g", Decimal(1000)),
    "ml": ("ml", Decimal(1)),
    "l": ("ml", Decimal(1000)),
    "un": ("unit", Decimal(1)),
    "unit": ("unit", Decimal(1)),
}
# "<container> <size><unit>", e.g. "balde 2kg", "un 500g", "un 100ml"
_PACKAGE = re.compile(r"^(?P<label>[a-zà-ú]+) (?P<size>\d+(?:[.,]\d+)?)(?P<unit>kg|g|ml|l)$", re.IGNORECASE)


class UnknownUnitError(ValueError):
    def __init__(self, raw: str):
        super().__init__(f"unknown unit: {raw!r}")
        self.raw = raw


class NonPositiveQuantityError(ValueError):
    def __init__(self, value):
        super().__init__(f"quantity must be > 0, got {value}")
        self.value = value


class IncompatibleUnitsError(ValueError):
    def __init__(self, from_base: str, to_base: str):
        super().__init__(f"cannot convert {from_base} to {to_base}")
        self.from_base = from_base
        self.to_base = to_base


@dataclass(frozen=True)
class UnitSpec:
    base_unit: str
    factor_to_base: Decimal
    package_label: str | None = None


def parse_unit(raw: str) -> UnitSpec:
    text = (raw or "").strip()
    if text.lower() in _SIMPLE:
        base_unit, factor = _SIMPLE[text.lower()]
        return UnitSpec(base_unit, factor)
    match = _PACKAGE.match(text)
    if not match:
        raise UnknownUnitError(raw)
    base_unit, factor = _SIMPLE[match["unit"].lower()]
    return UnitSpec(base_unit, Decimal(match["size"].replace(",", ".")) * factor, match["label"].lower())


def to_base(quantity: Decimal, raw_unit: str, expected_base_unit: str | None = None) -> Decimal:
    spec = parse_unit(raw_unit)
    if expected_base_unit is not None and spec.base_unit != expected_base_unit:
        raise IncompatibleUnitsError(spec.base_unit, expected_base_unit)
    if quantity <= 0:
        raise NonPositiveQuantityError(quantity)
    return quantity * spec.factor_to_base
