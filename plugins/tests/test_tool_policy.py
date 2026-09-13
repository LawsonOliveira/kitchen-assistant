"""Per-agent tool allowlists (D13) and the deterministic Confirmar click check (open question 10)."""

import json

import pytest

from sabor_guardrails import progress, tool_policy

READ = ["get_pantry", "get_state_summary", "check_pantry_match", "get_launch_menu"]
SKILLS = ["skill_view", "skills_list"]


def mcp(tools):
    return [f"mcp__costs__{tool}" for tool in tools]


MATRIX = {
    "fifi": ["clarify", "memory", "ask_recipe_expert", "ask_cost_expert", "ask_marketing_expert", *SKILLS, *mcp(READ)],
    "recipe_expert": ["research", *SKILLS, *mcp(READ + ["check_viability", "register_candidate_dish", "reject_candidate_dish",
                                                         "set_launch_batch_portions", "record_measure_quote", "confirm_measure", "confirm_dish_requirement", "accept_dish",
                                                         "update_kitchen_profile"])],
    "cost_expert": ["research", *SKILLS, *mcp(READ + ["compute_dish_cost", "check_budget_fit", "simulate_promotion", "record_price_quote",
                                                       "set_dish_packaging", "register_purchase", "adjust_budget", "correct_price",
                                                       "set_conversion_factor", "select_price_scenario", "import_pantry"])],
    "marketing_expert": ["research", *SKILLS, *mcp(READ + ["save_menu_copy", "register_promotion"])],
    # researcher fans out through fan_out_research (PLAN.md C17); its web children run under the same role.
    "researcher": ["web_search", "web_extract", "delegate_task", "fan_out_research", *SKILLS],
}
OTHERS = ["terminal", "write_file", "read_file", "execute_code", "skill_manage", "todo_list", "session_search", "send_message",
          "browser_navigate", "manage_connections", "image_generate", "a2a_call"]
ALL_TOOLS = sorted(set().union(*map(set, MATRIX.values())) | set(OTHERS))


@pytest.mark.parametrize("role", sorted(MATRIX))
def test_role_by_tool_matrix(role):
    for tool in ALL_TOOLS:
        decision = tool_policy.decide(role, tool)
        if tool in MATRIX[role]:
            assert decision is None, (role, tool)
        else:
            assert decision == {"action": "block", "message": tool_policy.BLOCKED_MESSAGE}, (role, tool)


def test_an_unknown_role_is_allowed_nothing():
    assert tool_policy.decide("", "clarify") == {"action": "block", "message": tool_policy.BLOCKED_MESSAGE}


def clarify_single(answer):
    return json.dumps({"question": "Confirma a compra?", "choices_offered": ["Confirmar", "Cancelar"], "user_response": answer})


def test_a_confirmation_needs_a_fresh_confirmar_click():
    ledger = tool_policy.ClickLedger()
    assert not ledger.consume("s1")
    ledger.record_clarify("s1", clarify_single("Confirmar (Recommended)"))
    assert ledger.consume("s1") and not ledger.consume("s1")


@pytest.mark.parametrize("answer", ["Cancelar", "Sim, pode comprar", "", "Confirmar preço estimado da maionese (R$ 15,39)",
                                    "[single-query mode: no user available to answer 'Confirma?'. Pick the best option]"])
def test_anything_but_the_confirmar_choice_is_not_a_click(answer):
    ledger = tool_policy.ClickLedger()
    ledger.record_clarify("s1", clarify_single(answer))
    assert not ledger.consume("s1")


def test_a_batch_clarify_gives_one_click_per_confirmar_answer():
    ledger = tool_policy.ClickLedger()
    ledger.record_clarify("s1", json.dumps({"responses": [{"question": "a", "user_response": "Confirmar"},
                                                          {"question": "b", "user_response": "Cancelar"},
                                                          {"question": "c", "user_response": "Confirmar (Recommended)"}]}))
    assert [ledger.consume("s1") for _ in range(3)] == [True, True, False]


def test_a_new_clarify_replaces_unused_clicks_and_sessions_are_separate():
    ledger = tool_policy.ClickLedger()
    ledger.record_clarify("s1", clarify_single("Confirmar"))
    ledger.record_clarify("s2", clarify_single("Confirmar"))
    ledger.record_clarify("s1", clarify_single("Cancelar"))
    assert not ledger.consume("s1") and ledger.consume("s2")


def test_fifi_cannot_send_owner_confirmation_without_a_click():
    ledger = tool_policy.ClickLedger()
    request = {"task": "register_purchase", "payload": {}, "owner_confirmation": {"choice": "Confirmar", "summary": "Comprar tomate"}}
    assert tool_policy.check_click(ledger, "s1", "ask_cost_expert", request) == {"action": "block", "message": tool_policy.CLICK_REQUIRED_MESSAGE}
    ledger.record_clarify("s1", clarify_single("Confirmar"))
    assert tool_policy.check_click(ledger, "s1", "ask_cost_expert", request) is None
    assert tool_policy.check_click(ledger, "s1", "ask_cost_expert", {"task": "match_and_cost", "payload": {"dish_id": 1}}) is None
    assert tool_policy.check_click(ledger, "s1", "clarify", {"question": "x"}) is None


def test_progress_messages_for_the_expert_tools():
    assert progress.progress_message("ask_recipe_expert") == "🔎 Tô procurando receitas…"
    assert progress.progress_message("ask_cost_expert") == "🧮 Fazendo as contas…"
    assert progress.progress_message("ask_marketing_expert") == "✍️ Escrevendo a descrição do prato…"
    assert progress.progress_message("clarify") is None
