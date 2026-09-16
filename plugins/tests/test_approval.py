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
    assert "- Carne moída: 500 g\n" in question
    assert "- Mandioca: 1,5 kg" in question and "- Alho: 3 dentes" in question  # her decimal, her plural
    assert "rende 8 porções" in question and "40 min" in question
    assert "lote de lançamento: 6" in question  # she chose 6; the recipe's own yield is another number
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
