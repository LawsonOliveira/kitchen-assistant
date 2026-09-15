"""A dish she refused never goes back to the research call (full run 20260915, scenario 09 trial 1)."""

import json

from kitchen_a2a import rejected


def test_a_rejected_dish_is_remembered_by_name_per_session():
    memory = rejected.RejectedDishes()
    memory.remember_candidate("s1", {"task": "register_candidate", "payload": {"recipe": {"name": "Frango Grelhado com Crosta"}}},
                              json.dumps({"result": {"dish": {"dish_id": 7, "status": "candidate"}}}))
    memory.remember_rejection("s1", {"task": "reject_candidate", "payload": {"dish_id": 7}})
    assert memory.names("s1") == ["Frango Grelhado com Crosta"]
    assert memory.names("s2") == []


def test_the_research_request_carries_every_dish_she_refused():
    # Scenario 09 trial 1: she rejected the grilled chicken with herb crust, Dona Sálvia asked for more ideas without
    # excluding it, and rejected_dish_not_suggested_again failed. The request now carries the name whether or not the
    # model remembered it.
    memory = rejected.RejectedDishes()
    memory.remember_candidate("s1", {"task": "register_candidate", "payload": {"recipe": {"name": "Frango Ensopado"}}},
                              json.dumps({"result": {"dish": {"dish_id": 3}}}))
    memory.remember_rejection("s1", {"task": "reject_candidate", "payload": {"dish_id": 3}})
    request = {"task": "suggest_dishes", "payload": {"pantry_focus": ["frango"], "owner_preferences": [],
                                                     "exclude_dish_names": ["Arroz de Frango"], "max_candidates": 3}}
    memory.exclude_in("s1", request)
    assert request["payload"]["exclude_dish_names"] == ["Arroz de Frango", "Frango Ensopado"]

    other = {"task": "normalize_recipe", "payload": {"owner_recipe_text": "..."}}
    memory.exclude_in("s1", other)
    assert other["payload"] == {"owner_recipe_text": "..."}  # only the research task is touched
