"""Per-turn cost cap aggregated across agents without a shared store (D37)."""

from decimal import Decimal

import pytest

from sabor_guardrails.cost_cap import CostCap, cost_of_call

PRICES = {"claude-haiku-4-5-20251001": ("1.00", "5.00"), "claude-sonnet-5": ("3.00", "15.00")}


def test_cap_minus_epsilon_passes_and_the_cap_blocks():
    cap = CostCap(Decimal("5.00"), agent="fifi")
    cap.start("t1")
    cap.add_own("t1", Decimal("4.99"))
    assert cap.allows_next_call("t1")
    cap.add_own("t1", Decimal("0.01"))
    assert not cap.allows_next_call("t1")


def test_spend_reported_by_experts_counts_for_the_turn():
    cap = CostCap(Decimal("0.06"), agent="fifi")
    cap.start("t1")
    cap.add_own("t1", Decimal("0.02"))
    assert cap.allows_next_call("t1") and cap.remaining("t1") == Decimal("0.04")
    cap.add_reported("t1", Decimal("0.05"), agent="cost_expert")
    assert not cap.allows_next_call("t1") and cap.remaining("t1") == Decimal("-0.01")
    assert cap.breakdown("t1") == {"fifi": "0.02", "cost_expert": "0.05"}


def test_an_expert_blocks_after_spending_the_remainder_it_received():
    cap = CostCap(Decimal("5.00"), agent="cost_expert")
    cap.start("t2", received_remaining=Decimal("0.01"))
    assert cap.allows_next_call("t2")
    cap.add_own("t2", Decimal("0.01"))
    assert not cap.allows_next_call("t2")


def test_turns_are_independent():
    cap = CostCap(Decimal("0.05"), agent="fifi")
    cap.start("t1")
    cap.add_own("t1", Decimal("0.05"))
    cap.start("t2")
    assert not cap.allows_next_call("t1") and cap.allows_next_call("t2")


def test_cost_of_a_call_from_tokens_and_the_price_table():
    assert cost_of_call("claude-haiku-4-5-20251001", 1_000_000, 200_000, PRICES) == Decimal("2.00")
    assert cost_of_call("claude-sonnet-5", 10_000, 1_000, PRICES) == Decimal("0.045")


def test_a_model_without_a_price_fails_loud():
    with pytest.raises(ValueError):
        cost_of_call("claude-unknown", 1, 1, PRICES)
