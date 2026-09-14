"""costs-mcp business operations (PLAN.md Loop 1).

Every operation takes a psycopg connection first. Writes run inside `conn.transaction()`, so a refused operation
writes nothing. Refusals are DomainError(code, message, details); the MCP server turns them into the error shape.
Money leaves this module only as display strings; raw Decimals stay inside (the agents never do arithmetic).
"""

import hashlib
import json
import math
import os
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from costs_mcp import db
from costs_mcp.measures import MissingConversionError, UnconfirmedMeasureError, resolve_measure
from costs_mcp.pantry_import import IngredientRecord, PantryImportError, diff, load_records, plain
from costs_mcp.pricing import (
    cmv_per_portion, format_brl, format_brl_min, format_unit_cost, min_price, min_price_with_packaging,
    price_alerts, price_scenarios, recipe_cmv, unit_cost,
)
from costs_mcp.units import NonPositiveQuantityError, UnknownUnitError, parse_unit, to_base

FEE_RATE = Decimal(os.environ.get("KITCHEN_PLATFORM_FEE_RATE", "0.10"))
CONTRACTS_DIR = Path(os.environ.get("KITCHEN_CONTRACTS_DIR") or Path(__file__).resolve().parents[3] / "contracts")
MAX_IMPORT_BYTES = 1_000_000
METRIC_UNITS = {"g", "kg", "ml", "l", "unit"}
PARAMETRIC = re.compile(r"^(stove_burners|max_batch_time_minutes|fridge_space_liters)>=(\d+)$")
PARAMETRIC_KEYS = {"stove_burners", "max_batch_time_minutes", "fridge_space_liters"}
FREE_TEXT_PREFIXES = ("gas_or_energy:", "other:")
UNIT_LABEL = {"g": "g", "ml": "ml", "unit": "un"}
STATUSES = ("available", "unavailable")


class DomainError(Exception):
    def __init__(self, code: str, message: str, **details):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details

    def as_error(self) -> dict:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


def _load_contracts():
    requirements = json.loads((CONTRACTS_DIR / "requirements.json").read_text())
    recipe = json.loads((CONTRACTS_DIR / "recipe.schema.json").read_text())
    registry = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in (requirements, recipe)])
    defs = requirements["$defs"]
    return Draft202012Validator(recipe, registry=registry), set(defs["equipment"]["enum"]), set(defs["technique"]["enum"])


RECIPE_VALIDATOR, EQUIPMENT, TECHNIQUES = _load_contracts()


# --- small helpers ---------------------------------------------------------------------------------------

def _decimal(value, field: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise DomainError("invalid_number", f"{field} must be a number, got {value!r}", field=field)


def _money(value, field: str) -> Decimal:
    amount = _decimal(value, field)
    if amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise DomainError("invalid_price", f"{field} must be a positive amount in whole cents, got {value!r}", field=field)
    return amount


def _quantity_base(quantity, unit: str) -> tuple[Decimal, str]:
    try:
        return to_base(_decimal(quantity, "quantity"), unit), parse_unit(unit).base_unit
    except UnknownUnitError:
        raise DomainError("invalid_unit", f"unknown unit {unit!r}", unit=unit)
    except NonPositiveQuantityError:
        raise DomainError("invalid_quantity", f"quantity must be > 0, got {quantity!r}", quantity=str(quantity))


def _dish(conn, dish_id) -> dict:
    dish = db.get_dish(conn, dish_id)
    if dish is None:
        raise DomainError("unknown_dish", f"dish {dish_id} does not exist", dish_id=dish_id)
    return dish


def _ingredient(conn, name: str) -> dict:
    row = db.ingredient_by_name(conn, name)
    if row is None:
        raise DomainError("unknown_ingredient", f"{name!r} is not a known ingredient", ingredient=name)
    return row


def _ingredient_or_create(conn, name: str, kind: str, base_unit: str) -> dict:
    row = db.ingredient_by_name(conn, name)
    if row is None:
        db.insert_ingredient(conn, name, base_unit, kind)
        return db.ingredient_by_name(conn, name)
    if row["base_unit"] != base_unit:
        raise DomainError("incompatible_units", f"{name!r} is measured in {row['base_unit']}, not {base_unit}",
                          ingredient=name, base_unit=row["base_unit"])
    return row


def _quantity_display(quantity: Decimal, base_unit: str) -> str:
    return f"{plain(quantity)} {UNIT_LABEL[base_unit]}"


# --- recipe lines: quantities in each ingredient's base unit ---------------------------------------------

def _to_ingredient_base(name: str, quantity: Decimal, unit: str, ingredient_base: str, factors: dict) -> Decimal:
    if unit == ingredient_base:
        return quantity
    direct = factors.get((name, unit))  # 1 <recipe unit> = amount <ingredient base>
    if direct and direct[1] == ingredient_base:
        return quantity * direct[0]
    reverse = factors.get((name, ingredient_base))  # 1 <ingredient base> = amount <recipe unit>
    if reverse and reverse[1] == unit:
        return quantity / reverse[0]
    raise MissingConversionError(name, ingredient_base)


def _resolve_lines(conn, recipe: dict):
    """(lines, unmatched names, conversions needed) — a line is one recipe ingredient in the ingredient's base unit."""
    factors, table = db.conversion_factors(conn), db.measures(conn)
    lines, unmatched, conversions = [], [], []
    for item in recipe["ingredients"]:
        name = item["pantry_match"] or item["name"]
        row = db.ingredient_by_name(conn, name)
        if row is None:
            unmatched.append(name)
            continue
        try:
            if item["unit"] in METRIC_UNITS:
                spec = parse_unit(item["unit"])
                quantity, unit, estimate = Decimal(str(item["quantity"])) * spec.factor_to_base, spec.base_unit, False
            else:
                count = Decimal(str(item["quantity"])) if item["quantity"] is not None else Decimal(1)
                quantity, unit, estimate = resolve_measure(name, item["unit"], count, factors, base_unit=row["base_unit"], table=table)
            quantity = _to_ingredient_base(name, quantity, unit, row["base_unit"], factors)
        except UnconfirmedMeasureError as error:
            conversions.append({"ingredient": error.ingredient, "measure": error.measure,
                                "estimate": {"amount_display": error.amount_display, "source_url": error.source_url}})
            continue
        except MissingConversionError as error:
            conversions.append({"ingredient": error.ingredient, "measure": error.measure})
            continue
        lines.append({"ingredient": row, "quantity_base": quantity, "is_estimate": estimate})
    return lines, unmatched, conversions


def _required_by_ingredient(lines, dish) -> dict[int, tuple[dict, Decimal]]:
    scale = Decimal(dish["launch_batch_portions"]) / Decimal(dish["yield_portions"])
    required: dict[int, tuple[dict, Decimal]] = {}
    for line in lines:
        row = line["ingredient"]
        previous = required.get(row["id"], (row, Decimal(0)))[1]
        required[row["id"]] = (row, previous + line["quantity_base"] * scale)
    return required


def _pantry_match(conn, dish) -> dict:
    lines, unmatched, conversions = _resolve_lines(conn, dish["recipe"])
    available = db.available_stock(conn)
    for ingredient_id, reserved in db.reservations(conn, dish["id"]).items():  # an accepted dish already holds its launch batch
        available[ingredient_id] = available.get(ingredient_id, Decimal(0)) + reserved
    have, missing = [], []
    for ingredient_id, (row, required) in _required_by_ingredient(lines, dish).items():
        free = available.get(ingredient_id, Decimal(0))
        if free >= required:
            have.append({"ingredient": row["name"], "required_display": _quantity_display(required, row["base_unit"]),
                         "available_display": _quantity_display(free, row["base_unit"])})
        else:
            missing.append({"ingredient": row["name"], "short_base": plain(required - free), "base_unit": row["base_unit"],
                            "short_display": _quantity_display(required - free, row["base_unit"])})
    # Every recipe line counts, a gosto included: a seasoning she does not have still has to be bought.
    counted = dish["recipe"]["ingredients"]
    coverage = Decimal(len(have)) / Decimal(len(counted)) * 100 if counted else Decimal(100)
    return {"have": have, "missing": missing, "unmatched": unmatched, "conversions_needed": conversions,
            "pantry_coverage_pct": int(coverage.quantize(Decimal(1), rounding=ROUND_HALF_UP))}


# --- viability -----------------------------------------------------------------------------------------------

def _requirement_state(requirement: dict, profile: dict) -> str:
    text = requirement["requirement"]
    if text.startswith(FREE_TEXT_PREFIXES):  # confirmed per dish, never matched against the global profile
        status = requirement["confirmation_status"]
        return "unknown" if status is None else ("ok" if status == "available" else "missing")
    match = PARAMETRIC.match(text)
    entry = profile.get(match[1] if match else text)
    if entry is None:
        return "unknown"
    if entry["status"] == "unavailable":
        return "missing"
    if match:
        return "ok" if entry["numeric_value"] is not None and entry["numeric_value"] >= Decimal(match[2]) else "missing"
    return "ok"


def _viability(conn, dish_id: int) -> dict:
    profile = db.kitchen_profile(conn)
    result = {"missing": [], "unknown": []}
    for requirement in db.dish_requirements(conn, dish_id):
        state = _requirement_state(requirement, profile)
        if state != "ok":
            result[state].append(requirement["requirement"])
    return result


def _require_viable(conn, dish_id: int) -> None:
    viability = _viability(conn, dish_id)
    if viability["missing"] or viability["unknown"]:
        raise DomainError("viability_failed", "the owner cannot cook this dish yet (missing or unknown requirements)", **viability)


def check_viability(conn, dish_id: int) -> dict:
    _dish(conn, dish_id)
    return _viability(conn, dish_id)


def update_kitchen_profile(conn, key: str, numeric_value, status: str, evidence: str) -> dict:
    if status not in STATUSES:
        raise DomainError("invalid_status", f"status must be one of {STATUSES}", status=status)
    if key in PARAMETRIC_KEYS:
        if numeric_value is None:
            raise DomainError("numeric_value_required", f"{key} needs a numeric value", key=key)
        value = _decimal(numeric_value, "numeric_value")
    elif key in EQUIPMENT or key in TECHNIQUES:
        value = None
    else:
        raise DomainError("unknown_requirement", f"{key!r} is not a kitchen-profile key of the vocabulary", key=key)
    with conn.transaction():
        db.upsert_kitchen_profile(conn, key, status, value, evidence)
    return {"requirement_key": key, "status": status}


# --- dish lifecycle ------------------------------------------------------------------------------------------

def register_candidate_dish(conn, recipe: dict, yield_portions: int, launch_batch_portions: int, evidence: str,
                            packaging_ingredient_name: str | None = None) -> dict:
    errors = sorted(RECIPE_VALIDATOR.iter_errors(recipe), key=str)
    if errors:
        raise DomainError("invalid_recipe", "recipe does not match contracts/recipe.schema.json", errors=[e.message for e in errors[:10]])
    if not all(isinstance(value, int) and value > 0 for value in (yield_portions, launch_batch_portions)):
        raise DomainError("invalid_portions", "yield_portions and launch_batch_portions must be positive integers")
    packaging_id = _packaging(conn, packaging_ingredient_name)["id"] if packaging_ingredient_name else None
    with conn.transaction():
        dish_id = db.insert_dish(conn, recipe, yield_portions, launch_batch_portions, packaging_id, evidence)
        for requirement in recipe["requirements"]:
            db.insert_dish_requirement(conn, dish_id, requirement, "recipe")
        # Derived so it never depends on the LLM remembering to emit it (D25).
        db.insert_dish_requirement(conn, dish_id, f"max_batch_time_minutes>={recipe['prep_time_minutes']}", "derived")
    return {"dish_id": dish_id, "viability": _viability(conn, dish_id), "pantry_match": _pantry_match(conn, _dish(conn, dish_id))}


def reject_candidate_dish(conn, dish_id: int, reason: str, evidence: str) -> dict:
    if _dish(conn, dish_id)["status"] != "candidate":
        raise DomainError("not_candidate", f"dish {dish_id} is not a candidate", dish_id=dish_id)
    with conn.transaction():
        db.reject_dish(conn, dish_id, reason)
    return {"dish_id": dish_id, "status": "rejected"}


def set_launch_batch_portions(conn, dish_id: int, launch_batch_portions: int, evidence: str) -> dict:
    """She may change how many portions a candidate launches with (PLAN.md open question 11); an accepted dish keeps the
    batch its stock reservation was made for. Her words are kept in audit_log."""
    if isinstance(launch_batch_portions, bool) or not isinstance(launch_batch_portions, int) or launch_batch_portions <= 0:
        raise DomainError("invalid_portions", "launch_batch_portions must be a positive integer")
    if _dish(conn, dish_id)["status"] != "candidate":
        raise DomainError("not_candidate", f"dish {dish_id} is not a candidate", dish_id=dish_id)
    with conn.transaction():
        db.set_launch_batch_portions(conn, dish_id, launch_batch_portions)
    return {"dish_id": dish_id, "launch_batch_portions": launch_batch_portions, "pantry_match": _pantry_match(conn, _dish(conn, dish_id))}


def confirm_dish_requirement(conn, dish_id: int, requirement: str, status: str, evidence: str) -> dict:
    if not requirement.startswith(FREE_TEXT_PREFIXES):
        raise DomainError("not_free_text_requirement", f"{requirement!r} is checked against the kitchen profile, not per dish",
                          requirement=requirement)
    if status not in STATUSES:
        raise DomainError("invalid_status", f"status must be one of {STATUSES}", status=status)
    _dish(conn, dish_id)
    with conn.transaction():
        if db.confirm_dish_requirement(conn, dish_id, requirement, status, evidence) == 0:
            raise DomainError("unknown_requirement", f"dish {dish_id} has no requirement {requirement!r}", requirement=requirement)
    return {"dish_id": dish_id, "requirement": requirement, "status": status}


def check_pantry_match(conn, dish_id: int) -> dict:
    return _pantry_match(conn, _dish(conn, dish_id))


def accept_dish(conn, dish_id: int) -> dict:
    dish = _dish(conn, dish_id)
    if dish["status"] != "candidate":
        raise DomainError("not_candidate", f"dish {dish_id} is not a candidate", dish_id=dish_id)
    _require_viable(conn, dish_id)
    lines, unmatched, conversions = _resolve_lines(conn, dish["recipe"])
    if unmatched:
        raise DomainError("missing_price_quote", "some ingredients are neither in the pantry nor quoted", ingredients=unmatched)
    if conversions:
        _refuse_conversions(conversions)
    required = _required_by_ingredient(lines, dish)
    available = db.available_stock(conn)
    shortfalls = [{"ingredient": row["name"], "short_base": plain(need - available.get(ingredient_id, Decimal(0))), "base_unit": row["base_unit"]}
                  for ingredient_id, (row, need) in required.items() if available.get(ingredient_id, Decimal(0)) < need]
    if shortfalls:
        raise DomainError("insufficient_stock", "buy the missing ingredients before accepting", shortfalls=shortfalls)
    _priced_lines(conn, lines, [])  # raises unconfirmed_price / missing_price_quote
    with conn.transaction():
        db.accept_dish(conn, dish_id)
        for ingredient_id, (_, need) in required.items():
            db.insert_reservation(conn, dish_id, ingredient_id, need)
    return {"dish_id": dish_id, "status": "accepted"}


def _packaging(conn, name: str) -> dict:
    row = _ingredient(conn, name)
    if row["kind"] != "packaging":
        raise DomainError("not_packaging", f"{name!r} is not a packaging item", ingredient=name)
    return row


def set_dish_packaging(conn, dish_id: int, packaging_ingredient_name: str, evidence: str) -> dict:
    _dish(conn, dish_id)
    row = _packaging(conn, packaging_ingredient_name)
    with conn.transaction():
        db.set_dish_packaging(conn, dish_id, row["id"])
    return {"dish_id": dish_id, "packaging": packaging_ingredient_name}


# --- prices, purchases, budget -------------------------------------------------------------------------

def record_price_quote(conn, ingredient_name: str, kind: str, package_quantity, package_unit: str, package_price,
                       source: str, source_url: str | None, evidence: str) -> dict:
    if source not in ("web_estimate", "owner_confirmed"):
        raise DomainError("invalid_source", "source must be web_estimate or owner_confirmed", source=source)
    if kind not in ("food", "packaging"):
        raise DomainError("invalid_kind", "kind must be food or packaging", kind=kind)
    quantity_base, base_unit = _quantity_base(package_quantity, package_unit)
    price = _money(package_price, "package_price")
    known = db.ingredient_by_name(conn, ingredient_name)
    current = db.current_price(conn, known["id"]) if known else None
    if source == "web_estimate" and current is not None and current["source"] != "web_estimate":
        # Estimates are only for missing items (D27): never replace a price from the spreadsheet or the owner.
        raise DomainError("price_already_known", f"{ingredient_name!r} already has a {current['source']} price",
                          ingredient=ingredient_name, price_source=current["source"],
                          unit_cost_display=format_unit_cost(current["total_price_paid"], current["quantity_purchased_base"], known["base_unit"]))
    with conn.transaction():
        row = _ingredient_or_create(conn, ingredient_name, kind, base_unit)
        db.supersede_price(conn, row["id"])
        db.insert_price(conn, row["id"], price, quantity_base, f"{plain(_decimal(package_quantity, 'package_quantity'))} {package_unit}",
                        source, source_url, evidence)
    # The package travels back so Dona Sálvia can confirm exactly this quote (Loop 3 scenario 02).
    return {"ingredient": ingredient_name, "price_source": source, "package_quantity": plain(_decimal(package_quantity, "package_quantity")),
            "package_unit": package_unit, "package_price": f"{price:.2f}", "package_price_display": format_brl(price),
            "unit_cost_display": format_unit_cost(price, quantity_base, base_unit)}


def register_purchase(conn, ingredient_name: str, kind: str, packages: int, package_quantity, package_unit: str,
                      package_price, price_source: str, source_url: str | None, dish_id: int | None, evidence: str) -> dict:
    if kind not in ("food", "packaging"):
        raise DomainError("invalid_kind", "kind must be food or packaging", kind=kind)
    if kind == "food" and dish_id is None:
        raise DomainError("dish_required", "food is bought only for a candidate or accepted dish")
    if dish_id is not None:
        if _dish(conn, dish_id)["status"] not in ("candidate", "accepted"):
            raise DomainError("not_candidate", f"dish {dish_id} is not a candidate or accepted dish", dish_id=dish_id)
        _require_viable(conn, dish_id)  # never buy for a dish she cannot cook (brief §2.2)
    if not isinstance(packages, int) or packages <= 0:
        raise DomainError("invalid_packages", "packages must be a positive integer", packages=packages)
    if price_source not in ("web_estimate", "owner_confirmed"):
        raise DomainError("invalid_source", "price_source must be web_estimate or owner_confirmed", price_source=price_source)
    quantity_base, base_unit = _quantity_base(package_quantity, package_unit)
    price = _money(package_price, "package_price")
    remaining = db.budget_status(conn)["remaining"]
    if price * packages > remaining:
        raise DomainError("budget_exceeded", "this purchase does not fit the remaining budget",
                          remaining_display=format_brl(remaining), shortfall_display=format_brl(price * packages - remaining))
    with conn.transaction():
        row = _ingredient_or_create(conn, ingredient_name, kind, base_unit)
        db.insert_purchase(conn, row["id"], dish_id, packages, quantity_base, price, price_source, source_url, evidence)
        db.supersede_price(conn, row["id"])  # latest-price rule
        db.insert_price(conn, row["id"], price, quantity_base, f"{plain(_decimal(package_quantity, 'package_quantity'))} {package_unit}",
                        "owner_confirmed", source_url, evidence)
    return {"ingredient": ingredient_name, "budget_remaining_display": format_brl(db.budget_status(conn)["remaining"])}


def adjust_budget(conn, delta, evidence: str) -> dict:
    amount = _decimal(delta, "delta")
    if amount == 0 or amount != amount.quantize(Decimal("0.01")):
        raise DomainError("invalid_delta", "delta must be a non-zero amount in whole cents", delta=str(delta))
    with conn.transaction():
        db.insert_budget_adjustment(conn, amount, evidence)
    return {"budget_remaining_display": format_brl(db.budget_status(conn)["remaining"])}


def check_budget_fit(conn, dish_id: int) -> dict:
    match = _pantry_match(conn, _dish(conn, dish_id))
    without_price = list(match["unmatched"])
    items, total = [], Decimal(0)
    for missing in match["missing"]:
        row = db.ingredient_by_name(conn, missing["ingredient"])
        price = db.current_price(conn, row["id"])
        if price is None:
            without_price.append(missing["ingredient"])
            continue
        packages = math.ceil(Decimal(missing["short_base"]) / price["quantity_purchased_base"])
        subtotal = price["total_price_paid"] * packages
        total += subtotal
        items.append({"ingredient": missing["ingredient"], "short_base": missing["short_base"], "base_unit": missing["base_unit"],
                      "package_quantity_base": plain(price["quantity_purchased_base"]), "packages_needed": packages,
                      "package_price_display": format_brl(price["total_price_paid"]), "subtotal_display": format_brl(subtotal),
                      "price_source": price["source"]})
    # Every gap goes in the first answer, so Dona Sálvia can ask the owner for all of them in one clarify.
    if without_price:
        raise DomainError("missing_price_quote", "quote these ingredients first", ingredients=without_price,
                          conversions=match["conversions_needed"])
    if match["conversions_needed"]:
        raise DomainError("missing_conversion", "ask the owner for a conversion factor",
                          ingredient=match["conversions_needed"][0]["ingredient"], conversions=match["conversions_needed"],
                          ingredients=[])
    remaining = db.budget_status(conn)["remaining"]
    return {"missing_items": items, "total_display": format_brl(total), "budget_remaining_display": format_brl(remaining),
            "budget_remaining_after_purchase_display": format_brl(remaining - total) if total <= remaining else None,
            "fits": total <= remaining, "shortfall_display": None if total <= remaining else format_brl(total - remaining)}


def set_conversion_factor(conn, ingredient_name: str, measure: str, amount, unit: str, evidence: str) -> dict:
    row = _ingredient(conn, ingredient_name)
    amount_base, amount_base_unit = _quantity_base(amount, unit)
    with conn.transaction():
        db.replace_conversion_factor(conn, row["id"], measure, amount_base, amount_base_unit, evidence)
    return {"ingredient": ingredient_name, "measure": measure, "amount_display": _quantity_display(amount_base, amount_base_unit)}


# --- cost, scenarios, alerts ---------------------------------------------------------------------------

def _normalized_words(text: str) -> list[str]:
    folded = unicodedata.normalize("NFKD", str(text).lower())
    return re.findall(r"[a-z0-9]+", "".join(char for char in folded if not unicodedata.combining(char)))


def cache_recipes(conn, recipes: list[dict], query: str) -> dict:
    """Researched web recipes kept for the next rounds and conversations (PL8); the owner's own recipes are never cached."""
    for recipe in recipes:
        errors = sorted(RECIPE_VALIDATOR.iter_errors(recipe), key=str)
        if errors:
            raise DomainError("invalid_recipe", "recipe does not match contracts/recipe.schema.json", errors=[e.message for e in errors[:10]])
        if not str(recipe["source_url"]).startswith(("http://", "https://")):
            raise DomainError("not_a_web_recipe", "only researched web recipes are cached", name=recipe["name"])
    with conn.transaction():
        for recipe in recipes:
            db.upsert_cached_recipe(conn, recipe, " ".join(_normalized_words(recipe["name"])), query)
    return {"cached": len(recipes)}


def find_cached_recipes(conn, query: str, exclude_dish_names: list[str] | None = None, limit: int = 3) -> dict:
    """Cached recipes whose title holds every word of the subject (case and accents ignored), newest first."""
    wanted = set(_normalized_words(query))
    excluded = {" ".join(_normalized_words(name)) for name in exclude_dish_names or []}
    found = [recipe for normalized, recipe in db.cached_recipes(conn)
             if wanted and wanted <= set(normalized.split()) and normalized not in excluded]
    return {"recipes": found[:max(1, min(int(limit), 10))]}


def _refuse_conversions(conversions: list[dict]) -> None:
    """Web measures waiting for her click are named as such (PL6); other gaps ask her for a conversion factor."""
    estimates = [conversion for conversion in conversions if "estimate" in conversion]
    if estimates:
        raise DomainError("unconfirmed_measure", "the owner must confirm or correct these web measures",
                          measures=[{"ingredient": c["ingredient"], "measure": c["measure"], **c["estimate"]} for c in estimates])
    raise DomainError("missing_conversion", "ask the owner for a conversion factor", ingredient=conversions[0]["ingredient"], conversions=conversions)


WEB_MEASURES = {"cup", "tablespoon", "teaspoon", "clove", "can", "package"}  # small estimates (pinch, a gosto) never go to the web


def _measure_result(ingredient_name: str, measure: str, amount: Decimal, unit: str, source: str, source_url: str | None) -> dict:
    return {"ingredient": ingredient_name, "measure": measure, "amount_display": f"{plain(Decimal(amount))} {unit}", "source": source,
            "source_url": source_url}


def record_measure_quote(conn, ingredient_name: str, measure: str, amount, unit: str, source_url: str | None, evidence: str) -> dict:
    """A household measure recipe_expert found on the web (PL6): stored as web_estimate, refused in CMV until confirm_measure."""
    if measure not in WEB_MEASURES:
        raise DomainError("unknown_measure", f"{measure!r} is not a measure to look up", measure=measure, allowed=sorted(WEB_MEASURES))
    if unit not in ("g", "ml"):
        raise DomainError("invalid_unit", "a measure is stored in g or ml", unit=unit)
    amount_base = _decimal(amount, "amount")
    if amount_base <= 0:
        raise DomainError("invalid_amount", f"amount must be > 0, got {amount!r}", amount=str(amount))
    table = db.measures(conn)
    known = next((table[key] for key in ((measure, ingredient_name), (measure, None)) if key in table and table[key]["source"] != "web_estimate"), None)
    if known is not None:  # the web only fills gaps, never replaces the D23 table or her confirmation
        raise DomainError("measure_already_known", f"{measure!r} of {ingredient_name!r} already converts", ingredient=ingredient_name,
                          measure=measure, **{k: v for k, v in _measure_result(ingredient_name, measure, known["amount"], known["unit"], known["source"], None).items() if k in ("amount_display", "source")})
    with conn.transaction():
        db.replace_measure(conn, measure, ingredient_name, amount_base, unit, "web_estimate", source_url, evidence)
    return _measure_result(ingredient_name, measure, amount_base, unit, "web_estimate", source_url)


def confirm_measure(conn, ingredient_name: str, measure: str, evidence: str) -> dict:
    """Her click on a web measure (PL6): from now on CMV uses it."""
    current = db.measures(conn).get((measure, ingredient_name))
    if current is None or current["source"] != "web_estimate":
        raise DomainError("no_measure_estimate", f"there is no web measure of {measure!r} for {ingredient_name!r} to confirm; "
                          "ask the owner how much it holds and send her number to set_conversion_factor instead of asking her to confirm again",
                          ingredient=ingredient_name, measure=measure)
    with conn.transaction():
        db.replace_measure(conn, measure, ingredient_name, current["amount"], current["unit"], "owner_confirmed", current["source_url"], evidence)
    return _measure_result(ingredient_name, measure, current["amount"], current["unit"], "owner_confirmed", current["source_url"])


def _priced_lines(conn, lines, unmatched) -> list[tuple[dict, dict]]:
    priced, without_price, unconfirmed = [], list(unmatched), []
    for line in lines:
        price = db.current_price(conn, line["ingredient"]["id"])
        if price is None:
            without_price.append(line["ingredient"]["name"])
        elif price["source"] == "web_estimate":
            unconfirmed.append(line["ingredient"]["name"])
        else:
            priced.append((line, price))
    if without_price:
        raise DomainError("missing_price_quote", "quote these ingredients first", ingredients=without_price)
    if unconfirmed:
        raise DomainError("unconfirmed_price", "the owner must confirm or correct these web estimates", ingredients=unconfirmed)
    return priced


def _cost(conn, recipe: dict, yield_portions: int, packaging_ingredient_id: int | None) -> dict:
    lines, unmatched, conversions = _resolve_lines(conn, recipe)
    if conversions:
        _refuse_conversions(conversions)
    priced = _priced_lines(conn, lines, unmatched)
    costed = [(line, price, line["quantity_base"] * unit_cost(price["total_price_paid"], price["quantity_purchased_base"])) for line, price in priced]
    total = recipe_cmv([(line["quantity_base"], unit_cost(price["total_price_paid"], price["quantity_purchased_base"])) for line, price in priced])
    packaging_cost = None
    if packaging_ingredient_id is not None:
        price = db.current_price(conn, packaging_ingredient_id)
        packaging_cost = unit_cost(price["total_price_paid"], price["quantity_purchased_base"])
    return {"costed": costed, "recipe_cmv": total, "per_portion": cmv_per_portion(total, yield_portions), "packaging_cost": packaging_cost}


def _dish_cost(conn, dish: dict) -> dict:
    return _cost(conn, dish["recipe"], dish["yield_portions"], dish["packaging_ingredient_id"])


def compute_dish_cost(conn, dish_id: int | None = None, recipe: dict | None = None) -> dict:
    if dish_id is not None:
        dish = _dish(conn, dish_id)
        cost, yield_portions = _dish_cost(conn, dish), dish["yield_portions"]
    elif recipe is not None:
        errors = list(RECIPE_VALIDATOR.iter_errors(recipe))
        if errors:
            raise DomainError("invalid_recipe", "recipe does not match contracts/recipe.schema.json", errors=[e.message for e in errors[:10]])
        cost, yield_portions = _cost(conn, recipe, recipe["yield_portions"], None), recipe["yield_portions"]
    else:
        raise DomainError("invalid_arguments", "pass dish_id or recipe")
    per_portion, packaging = cost["per_portion"], cost["packaging_cost"]
    lines = [{
        "ingredient": line["ingredient"]["name"],
        "quantity_used_display": _quantity_display(line["quantity_base"], line["ingredient"]["base_unit"]),
        "total_price_paid_display": format_brl(price["total_price_paid"]),
        "quantity_purchased_display": price["purchase_unit_label"],
        "unit_cost_display": format_unit_cost(price["total_price_paid"], price["quantity_purchased_base"], line["ingredient"]["base_unit"]),
        "cost_display": format_brl(amount),
        "price_source": price["source"],
        "is_estimate": line["is_estimate"],
    } for line, price, amount in cost["costed"]]
    return {
        "lines": lines,
        "recipe_cmv_display": format_brl(cost["recipe_cmv"]),
        "yield_portions": yield_portions,
        "cmv_per_portion_display": format_brl(per_portion),
        "min_price_display": format_brl_min(min_price(per_portion, FEE_RATE)),
        "packaging_unit_cost_display": None if packaging is None else format_brl(packaging),
        "min_price_with_packaging_display": None if packaging is None else format_brl_min(min_price_with_packaging(per_portion, packaging, FEE_RATE)),
        "scenarios": [{
            "target_cmv_pct": str(s.target_cmv_pct),
            "display_price": format_brl(s.display_price),
            "owner_receives_display": format_brl(s.owner_receives),
            "profit_display": format_brl(s.profit),
            "profit_after_packaging_display": None if s.profit_after_packaging is None else format_brl(s.profit_after_packaging),
            "margin_display": f"{(s.margin_on_sale * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%".replace(".", ","),
            "below_min": s.below_min,
        } for s in price_scenarios(per_portion, packaging, FEE_RATE)],
    }


def select_price_scenario(conn, dish_id: int, target_cmv_pct) -> dict:
    dish = _dish(conn, dish_id)
    if dish["status"] != "accepted":
        raise DomainError("not_accepted", f"dish {dish_id} must be accepted before choosing a price", dish_id=dish_id)
    target = _decimal(target_cmv_pct, "target_cmv_pct")
    cost = _dish_cost(conn, dish)
    scenario = next((s for s in price_scenarios(cost["per_portion"], cost["packaging_cost"], FEE_RATE) if s.target_cmv_pct == target), None)
    if scenario is None:
        raise DomainError("invalid_target", f"{target_cmv_pct} is not one of the offered scenarios", target_cmv_pct=str(target_cmv_pct))
    with conn.transaction():
        db.select_price_scenario(conn, dish_id, target, scenario.display_price)
    return {"dish_id": dish_id, "display_price": format_brl(scenario.display_price)}


def _alerts_for_accepted_dishes(conn) -> list[dict]:
    alerts = []
    for dish in db.dishes(conn, "accepted"):
        if dish["selected_price"] is None:
            continue
        cost = _dish_cost(conn, dish)
        for alert in price_alerts(cost["per_portion"], dish["selected_price"], dish["selected_target_cmv_pct"], FEE_RATE, cost["packaging_cost"]):
            alerts.append({"dish_id": dish["id"], "dish_name": dish["name"], "code": alert.code, "severity": alert.severity,
                           "actual_cmv_pct": str(alert.actual_cmv_pct.quantize(Decimal("0.0001"))),
                           "target_cmv_pct": str(alert.target_cmv_pct), "min_price_display": alert.min_price_display})
    return alerts


def correct_price(conn, ingredient_name: str, total_price_paid, quantity, unit: str, evidence: str) -> dict:
    row = _ingredient(conn, ingredient_name)
    quantity_base, base_unit = _quantity_base(quantity, unit)
    if base_unit != row["base_unit"]:
        raise DomainError("incompatible_units", f"{ingredient_name!r} is measured in {row['base_unit']}", ingredient=ingredient_name)
    price = _money(total_price_paid, "total_price_paid")
    with conn.transaction():
        db.supersede_price(conn, row["id"])
        db.insert_price(conn, row["id"], price, quantity_base, f"{plain(_decimal(quantity, 'quantity'))} {unit}", "owner_confirmed", None, evidence)
    return {"ingredient": ingredient_name, "unit_cost_display": format_unit_cost(price, quantity_base, base_unit),
            "alerts": _alerts_for_accepted_dishes(conn)}


# --- marketing ---------------------------------------------------------------------------------------------

def simulate_promotion(conn, dish_id: int, discount_pct) -> dict:
    dish = _dish(conn, dish_id)
    if dish["status"] != "accepted" or dish["selected_price"] is None:
        raise DomainError("not_accepted", "promotions are simulated on accepted dishes with a chosen price", dish_id=dish_id)
    discount = _decimal(discount_pct, "discount_pct")
    if not Decimal(0) < discount < Decimal(1):
        raise DomainError("invalid_discount", "discount_pct must be between 0 and 1", discount_pct=str(discount_pct))
    per_portion = _dish_cost(conn, dish)["per_portion"]
    promo_price = dish["selected_price"] * (Decimal(1) - discount)
    profit = promo_price * (Decimal(1) - FEE_RATE) - per_portion
    return {"promo_price_display": format_brl(promo_price), "profit_display": format_brl(profit),
            "margin_display": f"{(profit / promo_price * 100).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)}%".replace(".", ","),
            "below_min": promo_price < min_price(per_portion, FEE_RATE)}


def save_menu_copy(conn, dish_id: int, title: str, description: str, evidence: str) -> dict:
    _dish(conn, dish_id)
    if not 0 < len(title) <= 60 or not 0 < len(description) <= 250:
        raise DomainError("invalid_menu_copy", "title must have 1-60 chars and description 1-250 chars")
    with conn.transaction():
        db.upsert_menu_copy(conn, dish_id, title, description, evidence)
    return {"dish_id": dish_id, "title": title}


def register_promotion(conn, dish_id: int, description: str, discount_pct, evidence: str) -> dict:
    simulation = simulate_promotion(conn, dish_id, discount_pct)
    if simulation["below_min"]:
        raise DomainError("below_min", "this promotion sells below the minimum price", **simulation)
    with conn.transaction():
        promotion_id = db.insert_promotion(conn, dish_id, description, _decimal(discount_pct, "discount_pct"), evidence)
    return {"promotion_id": promotion_id, **simulation}


# --- pantry import -------------------------------------------------------------------------------------------

def _import_file(import_dir, file_path: str) -> Path:
    root, path = Path(import_dir).resolve(), Path(file_path).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != ".xlsx" or not path.is_file() or path.stat().st_size > MAX_IMPORT_BYTES:
        raise DomainError("invalid_import_path", "the file must be an .xlsx of at most 1 MB inside the import directory", file_path=file_path)
    return path


def _records(path: Path) -> list[IngredientRecord]:
    try:
        return load_records(path)
    except PantryImportError as error:
        raise DomainError("invalid_workbook", "the spreadsheet has problems; nothing was changed", errors=error.errors)


def import_pantry(conn, import_dir, file_path: str | None = None, import_id: int | None = None, apply: bool = False) -> dict:
    if apply:
        pending = db.get_pantry_import(conn, import_id) if import_id is not None else None
        if pending is None or pending["status"] != "previewed":
            raise DomainError("unknown_import", f"no previewed import {import_id}", import_id=import_id)
        path = Path(pending["file_path"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != pending["file_sha256"]:
            raise DomainError("import_file_changed", "the file changed after the preview; preview it again", import_id=import_id)
        records = _records(path)
        with conn.transaction():
            for record in records:
                row = _ingredient_or_create(conn, record.name, "food", record.base_unit)
                db.upsert_pantry_stock(conn, row["id"], record.stock_base)
                price = db.current_price(conn, row["id"])
                if price is None or (price["total_price_paid"], price["quantity_purchased_base"]) != (record.total_price_paid, record.quantity_purchased_base):
                    db.supersede_price(conn, row["id"])
                    db.insert_price(conn, row["id"], record.total_price_paid, record.quantity_purchased_base, record.purchase_unit_label, "spreadsheet")
            for name in {r["name"] for r in db.stocked_records(conn)} - {r.name for r in records}:
                db.upsert_pantry_stock(conn, db.ingredient_by_name(conn, name)["id"], Decimal(0))  # removed rows keep history
            db.mark_pantry_import_applied(conn, import_id)
        return {"import_id": import_id, "status": "applied"}
    if file_path is None:
        raise DomainError("invalid_arguments", "pass file_path to preview or import_id with apply=true")
    path = _import_file(import_dir, file_path)
    records = _records(path)
    current = [IngredientRecord(r["name"], r["base_unit"], r["stock_base"], r["total_price_paid"], r["quantity_purchased_base"],
                                r["purchase_unit_label"]) for r in db.stocked_records(conn)]
    changes = diff(current, records)
    with conn.transaction():
        new_id = db.insert_pantry_import(conn, str(path), hashlib.sha256(path.read_bytes()).hexdigest(), changes)
    return {"import_id": new_id, "diff": changes}


# --- reads ---------------------------------------------------------------------------------------------------

def get_pantry(conn) -> list[dict]:
    return [{"name": row["name"], "kind": row["kind"], "quantity_display": _quantity_display(row["quantity_base"], row["base_unit"]),
             "unit_cost_display": None if row["total_price_paid"] is None
             else format_unit_cost(row["total_price_paid"], row["quantity_purchased_base"], row["base_unit"]),
             "price_source": row["source"]} for row in db.pantry_rows(conn)]


def get_state_summary(conn) -> dict:
    budget = db.budget_status(conn)
    return {
        "budget_initial_display": format_brl(budget["initial_amount"]),
        "adjustments_total_display": format_brl(budget["adjustments_total"]),
        "purchases_total_display": format_brl(budget["purchases_total"]),
        "budget_remaining_display": format_brl(budget["remaining"]),
        "dishes": [{"id": d["id"], "name": d["name"], "status": d["status"],
                    "selected_price_display": None if d["selected_price"] is None else format_brl(d["selected_price"])} for d in db.dishes(conn)],
        "kitchen_profile": [{"requirement_key": key, "status": entry["status"],
                             "numeric_value": None if entry["numeric_value"] is None else plain(entry["numeric_value"])}
                            for key, entry in db.kitchen_profile(conn).items()],
    }


def get_launch_menu(conn) -> dict:
    menu = []
    for dish in db.dishes(conn, "accepted"):
        cost = _dish_cost(conn, dish)
        copy = db.menu_copy(conn, dish["id"]) or {}
        price = dish["selected_price"]
        profit = None if price is None else price * (Decimal(1) - FEE_RATE) - cost["per_portion"]
        menu.append({
            "name": dish["name"], "menu_title": copy.get("title"), "menu_description": copy.get("description"),
            "display_price": None if price is None else format_brl(price),
            "cmv_per_portion_display": format_brl(cost["per_portion"]),
            "profit_display": None if profit is None else format_brl(profit),
            "profit_after_packaging_display": None if profit is None or cost["packaging_cost"] is None else format_brl(profit - cost["packaging_cost"]),
        })
    shopping: dict[str, dict] = {}
    for purchase in db.purchases_with_dishes(conn):
        entry = shopping.setdefault(purchase["ingredient"], {
            "ingredient": purchase["ingredient"], "packages": 0, "subtotal": Decimal(0), "dish_names": [],
            "package_quantity_display": _quantity_display(purchase["package_quantity_base"], purchase["base_unit"])})
        entry["packages"] += purchase["packages"]
        entry["subtotal"] += purchase["packages"] * purchase["package_price"]
        if purchase["dish_name"] and purchase["dish_name"] not in entry["dish_names"]:
            entry["dish_names"].append(purchase["dish_name"])
    budget = db.budget_status(conn)
    return {
        "dishes": menu,
        "shopping_list": [{**{k: v for k, v in entry.items() if k != "subtotal"}, "subtotal_display": format_brl(entry["subtotal"])}
                          for entry in shopping.values()],
        "purchases_total_display": format_brl(budget["purchases_total"]),
        "budget_remaining_display": format_brl(budget["remaining"]),
    }
