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


def test_a_goodbye_that_ends_with_the_end_marker_ends_the_conversation():
    # Full run, scenario 01 trial 1: "... Obrigada mesmo!  FIM" did not end the conversation, and the persona and Dona
    # Sálvia exchanged goodbyes until the 14-message cap.
    transcript = [{"speaker": "orchestrator", "text": "Prontinho, Dona Maria!"}]
    assert simulated_owner.next_message(lambda system, messages: "Tá ótimo, Dona Sálvia! Obrigada mesmo!  FIM", SCENARIO, transcript) is None
    assert simulated_owner.next_message(lambda system, messages: "Então salva, e depois a gente vê o fim do mês.", SCENARIO,
                                        transcript) == "Então salva, e depois a gente vê o fim do mês."


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


def test_a_scenario_that_expects_no_purchase_tells_the_persona_she_will_not_buy():
    # Full run 20260913-192309, scenario 01 trials 1 and 3: the persona accepted dishes that needed caldo, margarina and
    # azeitonas and bought them (R$ 25,06), so "nothing was bought" and "budget untouched" failed even with judge means of
    # 3.5 and 4.75. Her profile only said she "accepts the first dish that uses only pantry ingredients".
    import re

    import yaml
    from pathlib import Path

    for path in sorted((Path(__file__).resolve().parents[1] / "scenarios").glob("*.yaml")):
        scenario = yaml.safe_load(path.read_text())
        # Only a check that forbids every purchase counts: scenario 02 asks that each purchase belongs to a dish.
        expects_no_purchase = any(re.fullmatch(r"select count\(\*\) = 0 from purchases", " ".join(check["sql"].lower().split()))
                                  for check in scenario["expected_state"])
        if not expects_no_purchase:
            continue
        behavior = [line.lower() for line in scenario["owner_profile"].get("behavior", [])]
        assert any(("buy" in line or "spend" in line) and any(word in line for word in ("never", "refuse", "does not", "no "))
                   for line in behavior), path.name
        # Her words are not enough: the clarify default answered Confirmar to "Posso registrar a compra ...?" and the
        # purchase went through anyway (full run 20260913-192309, scenario 01 trial 1 of the rerun).
        purchase = "Posso registrar a compra de 1 pacote de pimenta-do-reino (50g) por R$ 11,81?"
        assert simulated_owner.clarify_answer(scenario["clarify_answers"], purchase, ["Confirmar", "Cancelar"]) == {"choice": "Cancelar"}, path.name


def test_a_reply_without_text_ends_the_conversation_instead_of_crashing_the_run():
    # Full run 20260913-192309, scenario 02 trial 1: the persona's model answered with no text content and the runner died
    # with "'NoneType' object has no attribute 'strip'", losing the trial and stopping the whole run.
    transcript = [{"speaker": "orchestrator", "text": "Prontinho, Dona Maria!"}]
    assert simulated_owner.next_message(lambda system, messages: None, SCENARIO, transcript) is None
    assert simulated_owner.next_message(lambda system, messages: "   ", SCENARIO, transcript) is None
    assert simulated_owner.answer_clarify(lambda system, messages: None, SCENARIO, transcript,
                                          "Quantas porções?", []) == {"choice": ""}


def test_the_persona_is_never_asked_to_continue_her_own_last_message():
    # Full run 20260913-192309, scenario 02 trial 1: after a clarify the transcript ended with her own answer, so the
    # request ended with an assistant turn (a prefill) and the model replied with no text — the trial stopped at 13 turns.
    seen = {}

    def llm(system, messages):
        seen["messages"] = messages
        return "Sálvia, tá aí?"

    transcript = [{"speaker": "orchestrator", "text": "Quantos gramas tem uma batata?"},
                  {"speaker": "owner", "text": "[escolheu] Não sei direito não."}]
    assert simulated_owner.next_message(llm, SCENARIO, transcript) == "Sálvia, tá aí?"
    assert seen["messages"][-1]["role"] == "user"
    assert seen["messages"][-2] == {"role": "assistant", "content": "[escolheu] Não sei direito não."}


def test_a_price_choice_is_answered_by_value_not_by_position():
    # Full run 20260913-192309, scenario 07 trials 1 and 2: the three prices came listed from the dearest down, so
    # "choice_position: 2" picked R$ 7,90 while the scenario (and her own opening message) asked for R$ 9,90.
    prices = ["R$ 9,90 (30% CMV, lucro R$ 6,19/porção)", "R$ 7,90 (35% CMV)", "R$ 12,90 (25% CMV)"]
    answers = [{"question_contains": ["preço"], "choices_count": 3, "choice_contains": "9,90"}, {"default": "Confirmar"}]
    assert simulated_owner.clarify_answer(answers, "Qual preço?", prices) == {"choice_contains": "9,90"}
    assert simulated_owner.choice_index({"choice_contains": "9,90"}, prices) == 0
    for wanted, index in (("cheapest", 1), ("middle", 0), ("dearest", 2)):
        assert simulated_owner.choice_index({"choice_by_price": wanted}, prices) == index, wanted


def test_a_scenario_that_expects_one_accepted_dish_says_she_launches_only_that_dish():
    # Rerun of scenario 01 trial 2: the persona asked for a second dish (macarrão com bacon), the launch menu ended with
    # two, and "exactly one accepted dish with a chosen scenario and price" failed.
    import re

    import yaml
    from pathlib import Path

    for path in sorted((Path(__file__).resolve().parents[1] / "scenarios").glob("*.yaml")):
        scenario = yaml.safe_load(path.read_text())
        one_dish = any(re.search(r"count\(\*\) = 1 from dishes where status = 'accepted'", " ".join(check["sql"].lower().split()))
                       for check in scenario["expected_state"])
        if not one_dish:
            continue
        behavior = " ".join(scenario["owner_profile"].get("behavior", [])).lower()
        assert "only this one dish" in behavior, path.name


def test_the_persona_is_told_not_to_end_the_conversation_while_dona_salvia_is_working():
    # Rerun of scenario 01 trial 2: after her clarify answer the transcript ended with her own turn, the silence line was
    # all she saw, and she closed the conversation at nine turns with the dish still unregistered.
    prompt = simulated_owner.system_prompt(SCENARIO)
    assert "still working" in prompt and "never end the conversation because she is silent" in prompt


def test_no_scenario_requires_a_web_estimate_for_a_price_she_states():
    # Dona Sálvia now asks her what she pays before researching (correction C74), so a scenario whose owner knows the
    # price can no longer demand a web_estimate row: scenario 03 failed that check twice while doing the right thing.
    import yaml
    from pathlib import Path

    for path in sorted((Path(__file__).resolve().parents[1] / "scenarios").glob("*.yaml")):
        scenario = yaml.safe_load(path.read_text())
        facts = " ".join(fact["answer"] for fact in scenario.get("facts_to_reveal_only_if_asked", [])).lower()
        states_a_price = "r$" in facts and ("pago" in facts or "compro" in facts or "sai" in facts)
        if not states_a_price:
            continue
        sql = " ".join(check["sql"] for check in scenario["expected_state"])
        assert "web_estimate" not in sql, path.name
