"""Simulated Dona Maria (PLAN.md Loop 6 step 3b): clarify answers follow the scenario; free text comes from a Haiku
persona that reveals facts only when asked."""

import simulated_owner

SCENARIO = {
    "owner_profile": {"name": "Dona Maria", "persona": "52 anos, respostas curtas.", "goal": "Lançar um arroz com frango.",
                      "behavior": ["Aceita o primeiro prato só com a despensa."],
                      "opening_message": "Oi Dona Sálvia! Quero um arroz com frango."},
    "facts_to_reveal_only_if_asked": [{"topic": "oven", "answer": "Tenho forno a gás, mas não queria usar."},
                                      {"topic": "launch batch size", "answer": "No lançamento quero fazer 10 porções."}],
    "clarify_answers": [{"question_contains": ["preço"], "choice_position": 2},
                        {"question_contains": ["forno", "tem"], "choice": "Não"},
                        {"default": "Confirmar"}],
}


def test_the_first_clarify_entry_whose_words_all_appear_wins_then_the_default():
    answers = SCENARIO["clarify_answers"]
    assert simulated_owner.clarify_answer(answers, "Qual desses PREÇOS a senhora quer?") == {"choice_position": 2}
    assert simulated_owner.clarify_answer(answers, "A senhora tem forno em casa?") == {"choice": "Não"}
    assert simulated_owner.clarify_answer(answers, "Forno a gás?") == {"choice": "Confirmar"}


def test_an_answer_maps_to_a_choice_index_or_to_other_with_text():
    choices = ["Confirmar", "Cancelar"]
    assert simulated_owner.choice_index({"choice": "Confirmar"}, choices) == 0
    assert simulated_owner.choice_index({"choice_position": 2}, choices) == 1
    assert simulated_owner.choice_index({"choice": "não"}, ["Sim, tenho forno", "Não"]) == 1
    assert simulated_owner.choice_index({"choice": "Tenho só uma boca"}, choices) == ("other", "Tenho só uma boca")


def test_the_persona_prompt_lists_facts_as_reveal_only_when_asked():
    prompt = simulated_owner.system_prompt(SCENARIO)
    assert "Dona Maria" in prompt and "Lançar um arroz com frango." in prompt and "Aceita o primeiro prato" in prompt
    assert "oven: Tenho forno a gás, mas não queria usar." in prompt and "only when" in prompt


def test_next_message_sees_orchestrator_as_the_other_speaker_and_stops_on_the_end_marker():
    seen = {}

    def llm(system, messages):
        seen["system"], seen["messages"] = system, messages
        return "Quero 10 porções."

    transcript = [{"speaker": "owner", "text": "Oi Dona Sálvia! Quero um arroz com frango."},
                  {"speaker": "orchestrator", "text": "Quantas porções no lançamento?"}]
    assert simulated_owner.next_message(llm, SCENARIO, transcript) == "Quero 10 porções."
    assert seen["messages"] == [{"role": "assistant", "content": "Oi Dona Sálvia! Quero um arroz com frango."},
                                {"role": "user", "content": "Quantas porções no lançamento?"}]
    assert simulated_owner.next_message(lambda system, messages: " FIM ", SCENARIO, transcript) is None


def test_a_clarify_the_scenario_cannot_answer_goes_to_the_persona():
    # Live trial: orchestrator asked "Quantas porções ... no lançamento?" with choices 6 / 12; the default "Confirmar" matched no
    # choice, was typed as free text three times, and the flow looped until the clarify timed out.
    seen = {}

    def llm(system, messages):
        seen["system"], seen["messages"] = system, messages
        return "12 porções (dobro da receita)"

    answer = simulated_owner.answer_clarify(llm, SCENARIO, [], "Quantas porções no lançamento?", ["6 porções", "12 porções (dobro da receita)"])
    assert answer == {"choice": "12 porções (dobro da receita)"}
    assert "Quantas porções no lançamento?" in seen["messages"][-1]["content"] and "6 porções" in seen["messages"][-1]["content"]


def test_a_free_text_clarify_is_answered_by_the_persona_in_her_words():
    answer = simulated_owner.answer_clarify(lambda system, messages: "No lançamento quero fazer 10 porções.", SCENARIO, [],
                                            "Quantas porções você vai fazer?", [])
    assert answer == {"choice": "No lançamento quero fazer 10 porções."}


def test_a_scenario_answer_that_fits_the_choices_needs_no_model_call():
    def llm(system, messages):
        raise AssertionError("the scenario already answers this clarify")

    assert simulated_owner.answer_clarify(llm, SCENARIO, [], "Confirma o preço de R$ 9,90?", ["Confirmar", "Cancelar"]) == {"choice_position": 2}
    assert simulated_owner.answer_clarify(llm, SCENARIO, [], "Posso aceitar o prato?", ["Confirmar", "Cancelar"]) == {"choice": "Confirmar"}


def test_a_rule_with_choices_count_only_answers_a_prompt_with_that_many_choices():
    answers = [{"question_contains": ["preço"], "choices_count": 3, "choice_position": 2}, {"default": "Confirmar"}]
    prices = ["R$ 12,90 (CMV 35%)", "R$ 14,90 (CMV 30%)", "R$ 17,90 (CMV 25%)"]
    assert simulated_owner.clarify_answer(answers, "Qual preço a senhora escolhe?", prices) == {"choice_position": 2}
    assert simulated_owner.clarify_answer(answers, "Confirma o preço de R$ 14,90?", ["Confirmar", "Cancelar"]) == {"choice": "Confirmar"}


def test_no_scenario_takes_a_price_quote_confirmation_for_the_price_scenario_choice():
    # Smoke trial 01 (2026-09-13): "Posso usar o preço estimado de R$ 11,81 (pacote de 50g) para a pimenta-do-reino no
    # cálculo do custo do prato?" matched the rule meant for the three price scenarios (question_contains "preço",
    # choice_position 2), so the simulated owner clicked Cancelar four times and the flow never reached a price.
    import yaml
    from pathlib import Path

    question = "Posso usar o preço estimado de R$ 11,81 (pacote de 50g) para a pimenta-do-reino no cálculo do custo do prato?"
    for path in sorted((Path(__file__).resolve().parents[1] / "scenarios").glob("*.yaml")):
        answers = yaml.safe_load(path.read_text())["clarify_answers"]
        assert "choice_position" not in simulated_owner.clarify_answer(answers, question, ["Confirmar", "Cancelar"]), path.name


def test_the_persona_never_describes_her_pantry_beyond_the_facts():
    # Live trial: the persona said "sal e óleo eu tenho sim, salsinha no quintal", facts the scenario never gave.
    assert "pantry" in simulated_owner.system_prompt(SCENARIO)
