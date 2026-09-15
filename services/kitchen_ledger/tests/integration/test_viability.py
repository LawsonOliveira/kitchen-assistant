import pytest
from conftest import EVIDENCE, ingredient, make_recipe, viable_profile

from kitchen_ledger import operations
from kitchen_ledger.operations import DomainError

RICE = [ingredient("Arroz branco tipo 1", 100, "g")]


def candidate(conn, requirements=(), prep_time_minutes=30):
    recipe = make_recipe(RICE, requirements=requirements, prep_time_minutes=prep_time_minutes)
    return operations.register_candidate_dish(conn, recipe, 4, 4, EVIDENCE)["dish_id"]


def test_unknown_requirements_block_acceptance(conn):
    viable_profile(conn, oven=True)
    dish = candidate(conn, ["oven", "stove_burners>=2", "technique:bechamel", "other:maçarico"])
    viability = operations.check_viability(conn, dish)
    assert set(viability["unknown"]) == {"technique:bechamel", "other:maçarico"}
    assert viability["missing"] == []
    with pytest.raises(DomainError) as error:
        operations.accept_dish(conn, dish)
    assert error.value.code == "viability_failed"


def test_parametric_requirement_absent_is_unknown_and_lower_is_missing(conn):
    dish = candidate(conn, ["max_batch_time_minutes>=90"], prep_time_minutes=30)
    assert set(operations.check_viability(conn, dish)["unknown"]) == {"max_batch_time_minutes>=90", "max_batch_time_minutes>=30"}

    operations.update_kitchen_profile(conn, "max_batch_time_minutes", "60", "available", EVIDENCE)
    viability = operations.check_viability(conn, dish)
    assert viability == {"missing": ["max_batch_time_minutes>=90"], "unknown": []}


def test_batch_time_is_derived_from_prep_time(conn):
    operations.update_kitchen_profile(conn, "max_batch_time_minutes", "60", "available", EVIDENCE)
    dish = candidate(conn, prep_time_minutes=120)
    assert operations.check_viability(conn, dish)["missing"] == ["max_batch_time_minutes>=120"]


def test_unavailable_equipment_is_missing(conn):
    viable_profile(conn)
    operations.update_kitchen_profile(conn, "oven", None, "unavailable", "não tenho forno")
    dish = candidate(conn, ["oven"])
    assert operations.check_viability(conn, dish) == {"missing": ["oven"], "unknown": []}


def test_free_text_requirement_is_confirmed_per_dish(conn):
    viable_profile(conn)
    first = candidate(conn, ["gas_or_energy:botijão"])
    second = candidate(conn, ["gas_or_energy:botijão"])
    assert operations.check_viability(conn, first)["unknown"] == ["gas_or_energy:botijão"]

    operations.confirm_dish_requirement(conn, first, "gas_or_energy:botijão", "available", "tenho botijão")
    assert operations.check_viability(conn, first) == {"missing": [], "unknown": []}
    assert operations.check_viability(conn, second)["unknown"] == ["gas_or_energy:botijão"]

    operations.confirm_dish_requirement(conn, second, "gas_or_energy:botijão", "unavailable", "o gás acabou")
    assert operations.check_viability(conn, second)["missing"] == ["gas_or_energy:botijão"]


def test_only_free_text_requirements_are_confirmed_per_dish(conn):
    dish = candidate(conn, ["oven"])
    with pytest.raises(DomainError) as error:
        operations.confirm_dish_requirement(conn, dish, "oven", "available", EVIDENCE)
    assert error.value.code == "not_free_text_requirement"


@pytest.mark.parametrize(
    "key, numeric_value, code",
    [("sous_vide", None, "unknown_requirement"), ("other:maçarico", None, "unknown_requirement"),
     ("stove_burners", None, "numeric_value_required")],
)
def test_kitchen_profile_accepts_only_vocabulary_keys(conn, key, numeric_value, code):
    with pytest.raises(DomainError) as error:
        operations.update_kitchen_profile(conn, key, numeric_value, "available", EVIDENCE)
    assert error.value.code == code
