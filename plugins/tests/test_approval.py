"""She never approves what she has not read (owner's live session): the question carries the recipe and the menu copy."""

import json

from kitchen_guardrails import approval


RECIPE = {"task": "register_candidate", "payload": {
    "launch_batch_portions": 6,
    "recipe": {"name": "Escondidinho de carne moída", "yield_portions": 8, "prep_time_minutes": 40,
               "source_url": "https://exemplo.com/escondidinho",
               "ingredients": [{"name": "Carne moída", "quantity": 500, "unit": "g"},
                               {"name": "Mandioca", "quantity": 1.5, "unit": "kg"},
                               {"name": "Alho", "quantity": 3, "unit": "dente"}]}}}
MENU = json.dumps({"result": {"menu_copy": {"title": "Escondidinho da Dona Maria",
                                            "description": "Carne moída temperada sob purê de mandioca gratinado."}}})


def test_the_accept_question_lists_the_recipe_and_offers_the_method():
    # Live session: "Aceitar o Escondidinho de carne moída como prato do cardápio de lançamento?" and the recipe was
    # never on screen — she approved a dish she had not read. One ingredient per line, her own number format, and the
    # page the recipe came from is one click away, because the contract keeps it but never the steps.
    state = approval.Approvals()
    state.remember_request("s1", RECIPE)
    args = state.clarify_with_evidence("s1", {"questions": [{
        "question": "Aceitar o Escondidinho de carne moída como prato do cardápio de lançamento?",
        "choices": ["Confirmar", "Cancelar"]}]})
    question = args["questions"][0]["question"]
    # Everything scaled to the batch she will cook: 6 of the recipe's 8 portions is three quarters of each ingredient.
    assert "- Carne moída: 375 g\n" in question
    assert "- Mandioca: 1,125 kg" in question and "- Alho: 2,25 dentes" in question  # her decimal
    assert "lote de 6 porções" in question and "40 min" in question
    assert args["questions"][0]["choices"] == ["Confirmar", "Cancelar", "Ver a receita completa"]


def test_the_save_question_shows_the_title_and_the_description():
    # Same session: "Salvar essa descrição e título no cardápio do escondidinho?" with neither on screen.
    state = approval.Approvals()
    state.remember_result("s1", MENU)
    question = state.with_evidence("s1", "Salvar essa descrição e título no cardápio do escondidinho?")
    assert "Escondidinho da Dona Maria" in question and "purê de mandioca gratinado" in question


def test_a_question_that_already_shows_it_is_left_alone():
    state = approval.Approvals()
    state.remember_result("s1", MENU)
    asked = 'Salvar "Escondidinho da Dona Maria" com a descrição "Carne moída temperada sob purê de mandioca gratinado."?'
    assert state.with_evidence("s1", asked) == asked
    assert state.with_evidence("s1", "Quantas porções no lote?") == "Quantas porções no lote?"


def test_only_the_accept_question_gains_the_method_choice():
    state = approval.Approvals()
    state.remember_request("s1", RECIPE)
    other = {"questions": [{"question": "Quantas porções no lote?", "choices": ["4", "8"]}]}
    assert state.clarify_with_evidence("s1", other) == other


def test_a_batch_that_is_not_a_number_still_shows_her_the_recipe():
    # The batch reaches the guard as whatever the model wrote in the request ("6 porções", "", null). Scaling is a
    # convenience; the list is not. Nothing here may raise, because the exception would cost her the question itself.
    state = approval.Approvals()
    state.remember_request("s1", {"task": "register_candidate", "payload": {
        "launch_batch_portions": "6 porções", "recipe": RECIPE["payload"]["recipe"]}})
    question = state.with_evidence("s1", "Aceitar o Escondidinho de carne moída no cardápio?")
    assert "- Carne moída: 500 g" in question and "- Mandioca: 1,5 kg" in question  # unscaled, never missing


CANDIDATES = json.dumps({"result": {"candidates": [
    {"recipe": {"name": "Lasanha de carne moída"}, "pantry_coverage_pct": 69,
     "missing_ingredients": ["Massa de lasanha", "Creme de leite", "Presunto"]},
    {"recipe": {"name": "Escondidinho de carne moída"}, "pantry_coverage_pct": 100, "missing_ingredients": []},
    {"recipe": {"name": "Torta de frango"}, "pantry_coverage_pct": None, "missing_ingredients": ["Farinha"]}]}},
    ensure_ascii=False)


def test_the_choice_question_says_what_each_dish_is_missing():
    # Owner (2026-09-16): "não me falou os ingredientes que faltavam para cada receita". The expert answers with the
    # coverage and the missing list of every candidate; which dish she picks depends on what she would have to buy, so
    # those numbers belong in the question that offers the dishes, not in a paragraph the model may or may not write.
    state = approval.Approvals()
    state.remember_result("s1", CANDIDATES)
    args = state.clarify_with_evidence("s1", {"questions": [{
        "question": "Qual desses pratos a senhora gosta de cozinhar?",
        "choices": ["Lasanha de carne moída", "Escondidinho de carne moída"]}]})
    question = args["questions"][0]["question"]
    assert "Lasanha de carne moída: 69% da despensa. Falta comprar: Massa de lasanha, Creme de leite, Presunto." in question
    assert "Escondidinho de carne moída: 100% da despensa. Não falta nada." in question
    assert "Torta de frango" not in question  # a dish she was not offered is not explained


def test_a_question_that_offers_no_dish_keeps_its_own_words():
    state = approval.Approvals()
    state.remember_result("s1", CANDIDATES)
    other = {"questions": [{"question": "Quantas porções no lote?", "choices": ["4", "8"]}]}
    assert state.clarify_with_evidence("s1", other) == other


def test_a_shortened_choice_still_finds_its_dish():
    # The model writes the choices in its own words ("Lasanha", "Escondidinho"); the dish is the same one.
    state = approval.Approvals()
    state.remember_result("s1", CANDIDATES)
    args = state.clarify_with_evidence("s1", {"questions": [{
        "question": "Qual desses pratos a senhora gosta de cozinhar?", "choices": ["Lasanha", "Escondidinho"]}]})
    assert "Lasanha de carne moída: 69% da despensa." in args["questions"][0]["question"]
