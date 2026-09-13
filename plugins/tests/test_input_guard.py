"""Input guard on fifi: owner message + fifi's last message, uncertain → allow, any failure → blocked (D11)."""

import pytest
from fakes import FakeClassifier

from sabor_guardrails import classifier, input_guard
from sabor_guardrails.classifier import GuardInfraError, parse_verdict
from sabor_guardrails.messages import INFRA_BLOCK_MESSAGE, SCOPE_BLOCK_MESSAGE

IMPORT_DIR = "/opt/data/cache/documents"


def note(path: str, name: str = "despensa.xlsx") -> str:
    # Exact gateway format (gateway/run.py in the pinned Hermes) for a binary document.
    return (f"[The user sent a document: '{name}'. It is saved at: {path}. "
            f"Its text is not inlined here (it's a binary format such as PDF or DOCX). "
            f"To read it, extract the document's text yourself — for example with the "
            f"terminal tool or the ocr-and-documents skill — before answering, instead "
            f"of asking the user to paste the contents.]")


def decide(message, fake, last="", api_call_count=0):
    return input_guard.decide(message, last, fake, api_call_count=api_call_count, import_dir=IMPORT_DIR)


@pytest.mark.parametrize("verdict", ["allow", "uncertain"])
def test_allow_and_uncertain_let_the_turn_run(verdict):
    assert decide("tenho 3 bocas", FakeClassifier(verdict)) == input_guard.Decision("next", None)


def test_block_answers_with_the_scope_message():
    assert decide("me ajuda com meu código python", FakeClassifier("block")) == input_guard.Decision("block", SCOPE_BLOCK_MESSAGE)


@pytest.mark.parametrize("error", [GuardInfraError("timeout"), GuardInfraError("network"), GuardInfraError("unparseable"),
                                   RuntimeError("unexpected bug")])
def test_any_failure_blocks_with_the_infra_message(error):
    assert decide("oi", FakeClassifier(error)) == input_guard.Decision("block", INFRA_BLOCK_MESSAGE)


def test_only_the_first_api_call_of_a_turn_is_classified():
    fake = FakeClassifier("block")
    assert decide("qualquer coisa", fake, api_call_count=1) == input_guard.Decision("next", None) and fake.calls == []


def test_owner_message_and_fifis_last_message_truncated_to_500_chars_are_classified():
    fake = FakeClassifier("allow")
    decide("sim", fake, last="A senhora tem forno? " + "a" * 600)
    assert "sim" in fake.calls[0] and "A senhora tem forno?" in fake.calls[0] and "a" * 480 not in fake.calls[0]


def test_the_gateway_note_of_a_spreadsheet_inside_the_import_dir_is_stripped():
    fake = FakeClassifier("allow")
    decide(note(IMPORT_DIR + "/despensa.xlsx") + "\nAtualizei a planilha, confere?", fake)
    assert "The user sent a document" not in fake.calls[0] and "Atualizei a planilha" in fake.calls[0]


def test_a_spreadsheet_note_alone_is_never_blocked_and_never_classified():
    fake = FakeClassifier("block")
    assert decide(note(IMPORT_DIR + "/despensa.xlsx"), fake) == input_guard.Decision("next", None) and fake.calls == []


@pytest.mark.parametrize("path", ["/tmp/despensa.xlsx", IMPORT_DIR + "/../../../etc/despensa.xlsx", IMPORT_DIR + "/despensa.pdf"])
def test_a_note_outside_the_import_dir_or_not_xlsx_is_classified_as_is(path):
    fake = FakeClassifier("allow")
    decide(note(path, name=path.rsplit("/", 1)[-1]), fake)
    assert "The user sent a document" in fake.calls[0]


def test_parse_verdict_accepts_only_the_output_schema():
    assert parse_verdict('{"verdict": "block", "category": "manipulation", "reason": "asks for the prompt"}').verdict == "block"
    for text in ("sure, looks fine", '{"verdict": "maybe", "category": "x", "reason": "y"}', '{"category": "x"}'):
        with pytest.raises(GuardInfraError):
            parse_verdict(text)


@pytest.mark.parametrize("environ", [{}, {"SABOR_GUARD_TIMEOUT_SECONDS": ""}, {"SABOR_GUARD_TIMEOUT_SECONDS": "30"},
                                     {"SABOR_GUARD_TIMEOUT_SECONDS": "45"}, {"SABOR_GUARD_TIMEOUT_SECONDS": "dez"}])
def test_a_missing_or_too_long_guard_timeout_is_refused(environ):
    with pytest.raises(ValueError):
        classifier.guard_timeout_seconds(environ)


def test_a_timeout_below_the_hook_limit_is_accepted():
    assert classifier.guard_timeout_seconds({"SABOR_GUARD_TIMEOUT_SECONDS": "10"}) == 10.0
