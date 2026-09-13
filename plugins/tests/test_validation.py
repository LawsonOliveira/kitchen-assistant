"""Contract validation for A2A replies (PLAN.md D5, D6): invalid -> one retry with the errors -> explicit error."""

import json
from pathlib import Path

import pytest

from sabor_a2a import validation
from sabor_a2a.validation import ContractError

CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"
RESPONSE_SCHEMA = CONTRACTS / "research" / "recipe_search.response.json"
REQUEST = {"task_type": "recipe_search", "trace": {"trace_id": "t", "parent_span_id": "s", "turn_cost_remaining_usd": 4.5},
           "items": ["frango com arroz"]}
RECIPE = json.loads((CONTRACTS / "tests" / "fixtures" / "valid" / "recipe__reference_dish.json").read_text())
VALID = {"task_type": "recipe_search", "results": [RECIPE], "unverified_source": [], "cost_usd_spent": 0.01}


def test_valid_reply_is_parsed():
    assert validation.validate(RESPONSE_SCHEMA, json.dumps(VALID)) == VALID


def test_json_inside_a_markdown_fence_is_accepted():
    assert validation.validate(RESPONSE_SCHEMA, f"Aqui está:\n```json\n{json.dumps(VALID)}\n```") == VALID


@pytest.mark.parametrize("text", ["not json at all", json.dumps({"task_type": "recipe_search", "results": []})])
def test_invalid_reply_raises_with_errors(text):
    with pytest.raises(ContractError) as error:
        validation.validate(RESPONSE_SCHEMA, text)
    assert error.value.errors


def test_one_retry_with_the_validation_errors(monkeypatch):
    replies, sent = ["{}", json.dumps(VALID)], []

    def fake_send(peer_url, token, text, timeout_s):
        sent.append(text)
        return replies.pop(0)

    monkeypatch.setattr(validation, "send_message", fake_send)
    assert validation.call_with_contract("http://peer", "token", REQUEST, RESPONSE_SCHEMA, timeout_s=5) == VALID
    assert len(sent) == 2
    assert json.loads(sent[0]) == REQUEST
    assert "cost_usd_spent" in sent[1]  # the retry tells the peer what was wrong


def test_invalid_twice_becomes_contract_violation(monkeypatch):
    sent = []

    def fake_send(peer_url, token, text, timeout_s):
        sent.append(text)
        return "{}"

    monkeypatch.setattr(validation, "send_message", fake_send)
    result = validation.call_with_contract("http://peer", "token", REQUEST, RESPONSE_SCHEMA, timeout_s=5)
    assert result["error"]["code"] == "contract_violation"
    assert len(sent) == 2
