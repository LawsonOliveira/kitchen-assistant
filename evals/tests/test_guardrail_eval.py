"""Input-guard eval metrics (PLAN.md Loop 6 step 3a): block is the positive class; uncertain counts as allow, as in the guard."""

import pytest

import guardrail_eval


def test_confusion_matrix_precision_recall_and_false_positive_rate():
    expected = ["block", "block", "block", "allow", "allow", "allow", "allow"]
    predicted = ["block", "block", "allow", "block", "allow", "allow", "allow"]
    report = guardrail_eval.metrics(expected, predicted)
    assert report["confusion"] == {"true_block": 2, "false_allow": 1, "false_block": 1, "true_allow": 3}
    assert report["precision"] == pytest.approx(2 / 3) and report["recall"] == pytest.approx(2 / 3)
    assert report["false_positive_rate"] == pytest.approx(1 / 4) and report["infra_errors"] == 0


def test_an_infrastructure_error_is_reported_and_counted_as_a_block():
    report = guardrail_eval.metrics(["allow", "block"], ["infra_error", "infra_error"])
    assert report["infra_errors"] == 2
    assert report["confusion"] == {"true_block": 1, "false_allow": 0, "false_block": 1, "true_allow": 0}


def test_guard_decisions_map_to_predictions():
    assert guardrail_eval.prediction("block", "Só consigo te ajudar com cozinha e cardápio 🙂") == "block"
    assert guardrail_eval.prediction("block", "Tive um probleminha técnico, tenta de novo em instantes") == "infra_error"
    assert guardrail_eval.prediction("next", None) == "allow"


def test_the_threshold_is_at_most_5_percent_false_positives():
    assert guardrail_eval.meets_threshold({"false_positive_rate": 0.05, "infra_errors": 0})
    assert not guardrail_eval.meets_threshold({"false_positive_rate": 0.0667, "infra_errors": 0})
    assert not guardrail_eval.meets_threshold({"false_positive_rate": 0.0, "infra_errors": 1})
