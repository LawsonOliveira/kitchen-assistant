"""Simulated Dona Maria (PLAN.md Loop 6 step 3b): clarify answers follow the scenario; free text comes from a Haiku
persona that reveals facts only when asked."""

import simulated_owner

SCENARIO = {
    "owner_profile": {"name": "Dona Maria", "persona": "52 anos, respostas curtas.", "goal": "Lançar um arroz com frango.",
                      "behavior": ["Aceita o primeiro prato só com a despensa."],
                      "opening_message": "Oi Dona Fifi! Quero um arroz com frango."},
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


def test_next_message_sees_fifi_as_the_other_speaker_and_stops_on_the_end_marker():
    seen = {}

    def llm(system, messages):
        seen["system"], seen["messages"] = system, messages
        return "Quero 10 porções."

    transcript = [{"speaker": "owner", "text": "Oi Dona Fifi! Quero um arroz com frango."},
                  {"speaker": "fifi", "text": "Quantas porções no lançamento?"}]
    assert simulated_owner.next_message(llm, SCENARIO, transcript) == "Quero 10 porções."
    assert seen["messages"] == [{"role": "assistant", "content": "Oi Dona Fifi! Quero um arroz com frango."},
                                {"role": "user", "content": "Quantas porções no lançamento?"}]
    assert simulated_owner.next_message(lambda system, messages: " FIM ", SCENARIO, transcript) is None
