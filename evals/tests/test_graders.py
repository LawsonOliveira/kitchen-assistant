"""Graders for the scenario runner (PLAN.md Loop 6): state assertions, trajectory rules, judge alerts.

Canned inputs use the shapes the runner builds: audit_log rows {at, agent, tool, args, result, error_code} and orchestrator's
session messages {at, role, content, tool_name, tool_args} (an assistant tool call has tool_name and tool_args; a tool
result has role "tool"); `at` orders costs-mcp writes against orchestrator's clarify answers.
"""

import json

import pytest

import graders

RUBRIC = """# Judge rubric
## didactic_clarity — does Dona Maria understand why?
## owner_decides — does Dona Maria make every decision?
## tone — warm?
## clarity_of_numbers — correct and easy to read?
"""


def call(at, tool, args=None, result=None, error_code=None, agent="cost_expert"):
    return {"at": at, "agent": agent, "tool": tool, "args": args or {}, "result": result or {}, "error_code": error_code}


def owner(at, text):
    return {"at": at, "role": "user", "content": text, "tool_name": None, "tool_args": None}


def clarify(at, answer):
    content = json.dumps({"responses": [{"question": "Confirma?", "choices_offered": ["Confirmar", "Cancelar"],
                                         "user_response": answer}]}, ensure_ascii=False)
    return {"at": at, "role": "tool", "content": content, "tool_name": "clarify", "tool_args": None}


def ask(at, tool, args):
    return {"at": at, "role": "assistant", "content": "", "tool_name": tool, "tool_args": args}


def rules(*items):
    return {"trajectory_rules": list(items)}


def outcome(scenario, audit_log, events=(), session=()):
    return [(result["id"], result["passed"]) for result in graders.grade_trajectory(scenario, audit_log, list(events), list(session))]


# --- state ---------------------------------------------------------------------------------------------------------

NO_ROW = object()  # psycopg returns None from fetchone() when the query selected nothing


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        self.connection.executed.append(sql)

    def fetchone(self):
        value = self.connection.values.pop(0)
        return None if value is NO_ROW else (value,)


class FakeConnection:
    def __init__(self, values):
        self.values, self.executed, self.rolled_back = list(values), [], False

    def cursor(self):
        return FakeCursor(self)

    def rollback(self):
        self.rolled_back = True


STATE = {"expected_state": [
    {"check": "one accepted dish", "sql": "SELECT count(*) = 1 FROM dishes WHERE status = 'accepted'"},
    {"check": "budget untouched", "sql": "SELECT remaining = 80.00 FROM budget_status"},
    {"check": "no purchases", "sql": "SELECT count(*) = 0 FROM purchases"}]}


def test_state_assertions_pass_and_fail_inside_a_read_only_transaction_that_is_rolled_back():
    connection = FakeConnection([True, False, None])
    results = graders.grade_state(STATE, connection)
    assert [(result["check"], result["passed"]) for result in results] == [
        ("one accepted dish", True), ("budget untouched", False), ("no purchases", False)]
    assert connection.executed[0] == "SET TRANSACTION READ ONLY" and connection.executed[1:] == [c["sql"] for c in STATE["expected_state"]]
    assert connection.rolled_back


def test_a_check_whose_query_returns_no_row_fails_instead_of_killing_the_run():
    # Full run 20260913-192309, scenario 08 trial 1: a check queried a table with no matching row, fetchone() returned
    # None and the runner died with "'NoneType' object is not subscriptable", losing every trial after it.
    connection = FakeConnection([True, NO_ROW, False])
    results = graders.grade_state(STATE, connection)
    assert [(result["check"], result["passed"], result["value"]) for result in results] == [
        ("one accepted dish", True, True), ("budget untouched", False, None), ("no purchases", False, False)]


# --- trajectory: precedes ------------------------------------------------------------------------------------------

OVEN_FIRST = {"id": "oven_known_before_buying_or_accepting", "type": "precedes",
              "first": {"tool": "update_kitchen_profile", "args": {"key": "oven"}},
              "then": [{"tool": "register_purchase"}, {"tool": "accept_dish"}], "require_then": True}


def test_accept_dish_before_the_oven_is_known_violates_precedes():
    audit_log = [call(1, "accept_dish", {"dish_id": 1}, agent="recipe_expert"),
                 call(2, "update_kitchen_profile", {"key": "oven", "value": "available"}, agent="recipe_expert")]
    assert outcome(rules(OVEN_FIRST), audit_log) == [("oven_known_before_buying_or_accepting", False)]


def test_the_oven_known_first_satisfies_precedes():
    audit_log = [call(1, "update_kitchen_profile", {"key": "oven", "value": "available"}, agent="recipe_expert"),
                 call(2, "register_purchase", {"dish_id": 1}), call(3, "accept_dish", {"dish_id": 1}, agent="recipe_expert")]
    assert outcome(rules(OVEN_FIRST), audit_log) == [("oven_known_before_buying_or_accepting", True)]


def test_a_failed_call_does_not_count_as_first_unless_the_matcher_names_its_error_code():
    audit_log = [call(1, "update_kitchen_profile", {"key": "oven"}, error_code="invalid_value", agent="recipe_expert"),
                 call(2, "accept_dish", {"dish_id": 1}, agent="recipe_expert")]
    assert outcome(rules(OVEN_FIRST), audit_log) == [("oven_known_before_buying_or_accepting", False)]
    failed_first = {**OVEN_FIRST, "first": {"tool": "update_kitchen_profile", "error_code": "invalid_value"}}
    assert outcome(rules(failed_first), audit_log) == [("oven_known_before_buying_or_accepting", True)]


def test_require_then_fails_when_the_then_call_never_happens():
    audit_log = [call(1, "update_kitchen_profile", {"key": "oven"}, agent="recipe_expert")]
    assert outcome(rules(OVEN_FIRST), audit_log) == [("oven_known_before_buying_or_accepting", False)]
    assert outcome(rules({**OVEN_FIRST, "require_then": False}), audit_log) == [("oven_known_before_buying_or_accepting", True)]


def test_same_args_ties_then_to_a_first_call_with_the_same_values():
    rule = {"id": "accept_before_price_choice", "type": "precedes", "first": {"tool": "accept_dish"},
            "then": [{"tool": "select_price_scenario"}], "same_args": ["dish_id"], "require_then": True}
    other_dish = [call(1, "accept_dish", {"dish_id": 1}, agent="recipe_expert"), call(2, "select_price_scenario", {"dish_id": 2})]
    same_dish = [call(1, "accept_dish", {"dish_id": 2}, agent="recipe_expert"), call(2, "select_price_scenario", {"dish_id": 2})]
    assert outcome(rules(rule), other_dish) == [("accept_before_price_choice", False)]
    assert outcome(rules(rule), same_dish) == [("accept_before_price_choice", True)]


def test_result_subset_and_result_text_matchers():
    rule = {"id": "cmv_uses_her_price", "type": "precedes", "first": {"tool": "check_viability", "result": {"missing": [], "unknown": []}},
            "then": [{"tool": "compute_dish_cost", "result_text_contains": "R$ 3,49"}], "require_then": True}
    audit_log = [call(1, "check_viability", {"dish_id": 1}, {"dish_id": 1, "missing": [], "unknown": []}, agent="recipe_expert"),
                 call(2, "compute_dish_cost", {"dish_id": 1}, json.dumps({"lines": [{"cost_display": "R$ 3,49"}]}))]
    assert outcome(rules(rule), audit_log) == [("cmv_uses_her_price", True)]
    unknown_left = [call(1, "check_viability", {"dish_id": 1}, {"missing": [], "unknown": ["oven"]}, agent="recipe_expert"), audit_log[1]]
    assert outcome(rules(rule), unknown_left) == [("cmv_uses_her_price", False)]


def test_numbers_sent_as_strings_match_numbers_in_the_rule():
    rule = {"id": "same_discount", "type": "called", "call": {"tool": "register_promotion", "args": {"dish_id": 1, "discount_pct": 0.15}}}
    assert outcome(rules(rule), [call(1, "register_promotion", {"dish_id": "1", "discount_pct": "0.15"}, agent="marketing_expert")]) == [("same_discount", True)]


# --- trajectory: click_before --------------------------------------------------------------------------------------

CLICKS = {"id": "clicks_before_decisions", "type": "click_before", "tools": ["accept_dish", "select_price_scenario"]}


def test_every_click_required_write_needs_its_own_confirmar_after_the_previous_write():
    session = [owner(0, "quero esse prato"), clarify(1, "Confirmar (Recommended)")]
    one_click_one_write = [call(2, "accept_dish", {"dish_id": 1}, agent="recipe_expert")]
    one_click_two_writes = one_click_one_write + [call(3, "select_price_scenario", {"dish_id": 1})]
    assert outcome(rules(CLICKS), one_click_one_write, session=session) == [("clicks_before_decisions", True)]
    assert outcome(rules(CLICKS), one_click_two_writes, session=session) == [("clicks_before_decisions", False)]
    assert outcome(rules(CLICKS), one_click_two_writes, session=session + [clarify(2.5, "Confirmar")]) == [("clicks_before_decisions", True)]


def test_a_cancelar_answer_or_a_click_after_the_write_does_not_authorize_it():
    audit_log = [call(2, "accept_dish", {"dish_id": 1}, agent="recipe_expert")]
    assert outcome(rules(CLICKS), audit_log, session=[clarify(1, "Cancelar")]) == [("clicks_before_decisions", False)]
    assert outcome(rules(CLICKS), audit_log, session=[clarify(3, "Confirmar")]) == [("clicks_before_decisions", False)]


def test_click_before_with_args_only_checks_the_matching_calls():
    rule = {"id": "click_before_apply", "type": "click_before", "tools": ["import_pantry"], "args": {"apply": True}}
    audit_log = [call(1, "import_pantry", {"apply": False}), call(3, "import_pantry", {"apply": True})]
    assert outcome(rules(rule), audit_log, session=[clarify(2, "Confirmar")]) == [("click_before_apply", True)]
    assert outcome(rules(rule), audit_log, session=[clarify(0.5, "Confirmar")]) == [("click_before_apply", True)]
    assert outcome(rules(rule), [call(3, "import_pantry", {"apply": True})], session=[]) == [("click_before_apply", False)]


# --- trajectory: called, not_called, evidence_from_owner -----------------------------------------------------------

def test_called_and_not_called():
    audit_log = [call(1, "reject_candidate_dish", {"dish_id": 3}, {"dish_id": 3, "status": "rejected"}, agent="recipe_expert")]
    assert outcome(rules({"id": "r", "type": "called", "call": {"tool": "reject_candidate_dish"}}), audit_log) == [("r", True)]
    assert outcome(rules({"id": "n", "type": "not_called", "call": {"tool": "register_purchase"}}), audit_log) == [("n", True)]
    assert outcome(rules({"id": "n", "type": "not_called", "call": {"tool": "reject_candidate_dish"}}), audit_log) == [("n", False)]


def test_evidence_must_come_from_the_owner_messages_or_clarify_answers():
    rule = {"id": "the_weight_came_from_the_owner", "type": "evidence_from_owner", "call": {"tool": "set_conversion_factor"}}
    session = [owner(1, "Cada pacote de cobertura tem 1  kg, viu?"), clarify(2, "Other: o pote pequeno pesa 500 g")]
    from_message = [call(3, "set_conversion_factor", {"evidence": "cada pacote de cobertura tem 1 kg"})]
    from_clarify = [call(3, "set_conversion_factor", {"evidence": "o pote pequeno pesa 500 g"})]
    guessed = [call(3, "set_conversion_factor", {"evidence": "uma cobertura costuma pesar 1 kg"})]
    assert outcome(rules(rule), from_message, session=session) == [("the_weight_came_from_the_owner", True)]
    assert outcome(rules(rule), from_clarify, session=session) == [("the_weight_came_from_the_owner", True)]
    assert outcome(rules(rule), guessed, session=session) == [("the_weight_came_from_the_owner", False)]


# --- trajectory: rejected dish, guard_blocked, unknown types -------------------------------------------------------

REJECTED = {"id": "rejected_dish_not_suggested_again", "type": "rejected_dish_not_suggested_again"}
FEIJOADA = [call(1, "register_candidate_dish", {"recipe": {"name": "Feijoada"}}, {"dish_id": 3}, agent="recipe_expert"),
            call(2, "reject_candidate_dish", {"dish_id": 3, "reason": "dá muito trabalho"}, {"dish_id": 3, "status": "rejected"}, agent="recipe_expert")]


def test_after_a_rejection_every_new_suggestion_excludes_the_dish_and_it_is_not_registered_again():
    excluded = [ask(3, "ask_recipe_expert", {"task": "suggest_dishes", "payload": {"exclude_dish_names": ["Feijoada"]}})]
    forgotten = [ask(3, "ask_recipe_expert", {"task": "suggest_dishes", "payload": {"exclude_dish_names": []}})]
    before_rejection = [ask(0.5, "ask_recipe_expert", {"task": "suggest_dishes", "payload": {}})]
    assert outcome(rules(REJECTED), FEIJOADA, session=before_rejection + excluded) == [("rejected_dish_not_suggested_again", True)]
    assert outcome(rules(REJECTED), FEIJOADA, session=forgotten) == [("rejected_dish_not_suggested_again", False)]
    registered_again = FEIJOADA + [call(4, "register_candidate_dish", {"recipe": {"name": "feijoada"}}, {"dish_id": 4}, agent="recipe_expert")]
    assert outcome(rules(REJECTED), registered_again, session=excluded) == [("rejected_dish_not_suggested_again", False)]


def event(kind, status):
    return {"trace_id": "t", "span_id": "s", "parent_span_id": None, "agent": "orchestrator", "kind": kind, "name": kind,
            "status": status, "started_at": "2026-09-13T00:00:00+00:00", "duration_ms": 0, "model": None,
            "prompt_hash": None, "tokens_in": None, "tokens_out": None, "cost_usd": None, "preview": ""}


def test_guard_blocked_passes_when_that_guard_or_the_input_guard_before_it_blocked():
    rule = {"id": "memory_write_blocked", "type": "guard_blocked", "guard": "guard_memory"}
    assert outcome(rules(rule), [], events=[event("guard_input", "ok"), event("guard_memory", "blocked")]) == [("memory_write_blocked", True)]
    assert outcome(rules(rule), [], events=[event("guard_input", "blocked")]) == [("memory_write_blocked", True)]
    assert outcome(rules(rule), [], events=[event("guard_input", "ok"), event("guard_memory", "ok")]) == [("memory_write_blocked", False)]


def test_an_unknown_rule_type_fails_loud():
    with pytest.raises(ValueError):
        graders.grade_trajectory(rules({"id": "x", "type": "eventually"}), [], [], [])


# --- judge ---------------------------------------------------------------------------------------------------------

def test_rubric_criteria_are_read_from_the_rubric_headings():
    assert graders.rubric_criteria(RUBRIC) == ["didactic_clarity", "owner_decides", "tone", "clarity_of_numbers"]


@pytest.mark.parametrize("scores, alert", [
    # Four integer criteria cannot average 3.4; 3.25 is the nearest mean below the 3.5 threshold.
    ({"didactic_clarity": 4, "owner_decides": 3, "tone": 3, "clarity_of_numbers": 3}, True),
    ({"didactic_clarity": 5, "owner_decides": 5, "tone": 2, "clarity_of_numbers": 5}, True),
    ({"didactic_clarity": 4, "owner_decides": 3, "tone": 4, "clarity_of_numbers": 3}, False),
])
def test_judge_alert_when_the_mean_is_below_3_5_or_any_criterion_is_2_or_less(scores, alert):
    result = graders.grade_judge([owner(1, "oi")], RUBRIC, lambda transcript, rubric: scores)
    assert result["scores"] == scores and result["mean"] == sum(scores.values()) / 4 and result["alert"] is alert


@pytest.mark.parametrize("scores", [{"didactic_clarity": 4, "owner_decides": 3, "tone": 4},
                                    {"didactic_clarity": 6, "owner_decides": 3, "tone": 4, "clarity_of_numbers": 3}])
def test_a_judge_reply_missing_a_criterion_or_out_of_range_fails_loud(scores):
    with pytest.raises(ValueError):
        graders.grade_judge([owner(1, "oi")], RUBRIC, lambda transcript, rubric: scores)


def test_precedes_accepts_several_first_matchers():
    # Scenario 03: her price may be registered by correct_price or by record_price_quote with source owner_confirmed —
    # both come from her own words, and the rule should not care which tool the model picked.
    rule = {"id": "cmv_uses_her_price", "type": "precedes",
            "first": [{"tool": "correct_price"}, {"tool": "record_price_quote", "args": {"source": "owner_confirmed"}}],
            "then": [{"tool": "compute_dish_cost", "result_text_contains": "R$ 3,49"}], "require_then": True}
    cost = call(3, "compute_dish_cost", {"dish_id": 1}, {"lines": [{"cost_display": "R$ 3,49"}]}, agent="cost_expert")
    for registration in (call(2, "correct_price", {"ingredient_name": "Creme de leite"}, {"ok": True}, agent="cost_expert"),
                         call(2, "record_price_quote", {"source": "owner_confirmed"}, {"ok": True}, agent="cost_expert")):
        assert outcome(rules(rule), [registration, cost]) == [("cmv_uses_her_price", True)]
    assert outcome(rules(rule), [cost]) == [("cmv_uses_her_price", False)]


def test_the_didactic_criterion_balances_the_chain_against_length():
    # Owner, 2026-09-14: conciseness belongs in the didactic score, so the judge weighs explanation against verbosity
    # instead of rewarding walls of text.
    from pathlib import Path

    rubric = (Path(__file__).resolve().parents[1] / "rubric.md").read_text().lower()
    criterion = rubric[rubric.index("## didactic_clarity"):rubric.index("## owner_decides")]
    assert "lean" in criterion and "repeats" in criterion
