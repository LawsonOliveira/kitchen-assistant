"""Deterministic R$ grounding: every amount Dona Fifi shows must come from an expert display string (D12)."""

import json

import pytest

from sabor_guardrails.grounding import SessionGrounding, extract_brl


@pytest.mark.parametrize(
    "text, expected",
    [("Preço: R$ 7,90 por porção", {"R$ 7,90"}),
     ("Total R$ 1.234,56 e sobra R$ 80,00", {"R$ 1.234,56", "R$ 80,00"}),
     ("Arroz R$ 4,98/kg, óleo R$ 9,00/L e ovos R$ 0,80/un", {"R$ 4,98/kg", "R$ 9,00/L", "R$ 0,80/un"}),
     ("Sem espaço: R$7,90 e com espaço fino: R$ 10,90", {"R$ 7,90", "R$ 10,90"}),
     ("Só 3 porções, 35% de CMV e 45 minutos", set())],
)
def test_extract_brl(text, expected):
    assert extract_brl(text) == expected


def expert_reply():
    return json.dumps({"result": {"recipe_cmv_display": "R$ 10,86", "lines": [{"unit_cost_display": "R$ 4,98/kg"}],
                                  "scenarios": [{"display_price": "R$ 7,90", "profit_display": "R$ 4,39"}]},
                       "questions_for_owner": [], "cost_usd_spent": 0.0})


def test_display_strings_from_expert_results_ground_the_answer():
    grounding = SessionGrounding()
    grounding.add_from_tool_result(expert_reply())
    assert grounding.ungrounded("Vende por R$ 7,90, lucro R$ 4,39; o arroz sai R$ 4,98/kg (CMV R$ 10,86)") == set()
    assert grounding.ungrounded("Ou quem sabe R$ 12,34?") == {"R$ 12,34"}


def test_an_amount_is_grounded_with_or_without_its_unit_suffix():
    grounding = SessionGrounding()
    grounding.add_from_tool_result(expert_reply())
    assert grounding.ungrounded("o arroz sai R$ 4,98 o quilo") == set()


def test_mcp_envelopes_with_json_text_are_decoded():
    grounding = SessionGrounding()
    grounding.add_from_tool_result(json.dumps({"result": json.dumps({"budget_remaining_display": "R$ 64,00"})}))
    assert grounding.ungrounded("Sobram R$ 64,00") == set()


def test_only_display_fields_ground_an_amount():
    grounding = SessionGrounding()
    grounding.add_from_tool_result({"result": {"note": "R$ 5,00", "questions_for_owner": ["Paga R$ 5,00?"]}})
    assert grounding.ungrounded("R$ 5,00") == {"R$ 5,00"}


def test_the_initial_budget_is_always_grounded():
    assert SessionGrounding().ungrounded("A senhora tem R$ 80,00 de orçamento") == set()


def test_amounts_dona_maria_typed_in_the_session_ground_the_answer():
    # Live API-server turn: she wrote "paguei R$ 2,99" and Dona Fifi's question repeating her price before registering
    # the purchase was blocked as an invented amount.
    grounding = SessionGrounding()
    grounding.add_owner_message("quero registrar 1 caixinha de creme de leite, paguei R$ 2,99")
    assert grounding.ungrounded("Vou registrar 1 caixinha por R$ 2,99 e o total fica R$ 5,98, pode confirmar?") == {"R$ 5,98"}
