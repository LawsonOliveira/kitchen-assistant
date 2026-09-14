"""Output verifier on orchestrator: deterministic grounding first, then the policy; uncertain or any failure → blocked (D12)."""

import pytest
from fakes import FakeClassifier

from kitchen_guardrails import messages, output_guard
from kitchen_guardrails.classifier import GuardInfraError
from kitchen_guardrails.grounding import SessionGrounding
from kitchen_guardrails.messages import INFRA_BLOCK_MESSAGE, NUMBER_BLOCK_MESSAGE, SCOPE_BLOCK_MESSAGE


def grounding():
    session = SessionGrounding()
    session.add_from_tool_result({"result": {"display_price": "R$ 7,90", "unit_cost_display": "R$ 4,98/kg"}})
    return session


def test_ungrounded_money_is_blocked_before_asking_the_policy():
    fake = FakeClassifier("allow")
    assert output_guard.review("Dá pra vender por R$ 12,34", grounding(), fake, platform="cli") == NUMBER_BLOCK_MESSAGE
    assert fake.calls == []


def test_grounded_answer_is_returned_unchanged_when_the_policy_allows():
    text = "Vende por R$ 7,90; o arroz sai R$ 4,98/kg"
    assert output_guard.review(text, grounding(), FakeClassifier("allow"), platform="cli") == text


@pytest.mark.parametrize("verdict", ["block", "uncertain"])
def test_policy_block_or_uncertain_blocks(verdict):
    assert output_guard.review("Esse prato emagrece!", grounding(), FakeClassifier(verdict), platform="telegram") == SCOPE_BLOCK_MESSAGE


@pytest.mark.parametrize("error", [GuardInfraError("timeout"), RuntimeError("bug")])
def test_policy_failure_blocks_with_the_infra_message(error):
    assert output_guard.review("Oi, Dona Maria!", grounding(), FakeClassifier(error), platform="cli") == INFRA_BLOCK_MESSAGE


def test_a_broken_grounding_still_returns_a_string():
    class Broken:
        def ungrounded(self, text):
            raise RuntimeError("bug")

    assert output_guard.review("R$ 7,90", Broken(), FakeClassifier("allow"), platform="cli") == INFRA_BLOCK_MESSAGE


def test_subagent_summaries_are_not_reviewed():
    assert output_guard.review("R$ 12,34", grounding(), FakeClassifier("block"), platform="subagent") is None


def test_fixed_messages_match_the_plan():
    assert messages.SCOPE_BLOCK_MESSAGE == "Só consigo te ajudar com cozinha e cardápio 🙂"
    assert messages.INFRA_BLOCK_MESSAGE == "Tive um probleminha técnico, tenta de novo em instantes"
    assert messages.COST_CAP_MESSAGE == "Essa conversa ficou comprida demais pra mim agora. Vamos recomeçar por partes?"
    assert messages.MEMORY_BLOCK_MESSAGE == "memória recusada"
    assert messages.PROGRESS == {"ask_recipe_expert": "🔎 Tô procurando receitas…", "ask_cost_expert": "🧮 Fazendo as contas…",
                                 "ask_marketing_expert": "✍️ Escrevendo a descrição do prato…"}


def test_an_ungrounded_amount_gets_its_own_message_not_the_scope_one():
    # Probe of 19:01, scenario 04: after her click, Dona Sálvia's reply carried an amount she had computed herself, the
    # verifier blocked it and the owner read "Só consigo te ajudar com cozinha e cardápio 🙂" — as if her purchase were
    # off topic. Tone scored 3 and clarity of numbers 2 in that trial.
    from kitchen_guardrails.messages import NUMBER_BLOCK_MESSAGE

    def allow(_text):
        class Verdict:
            verdict = "allow"
        return Verdict()

    assert output_guard.review("Dá pra vender por R$ 12,34", grounding(), allow, platform="cli") == NUMBER_BLOCK_MESSAGE
    assert NUMBER_BLOCK_MESSAGE != SCOPE_BLOCK_MESSAGE and "conferir" in NUMBER_BLOCK_MESSAGE
