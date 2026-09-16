"""She never approves what she has not read (owner's live session): the question carries the recipe and the menu copy."""

import json

from kitchen_guardrails import approval


RECIPE = {"task": "register_candidate", "payload": {"recipe": {
    "name": "Escondidinho de carne moída", "yield_portions": 8,
    "ingredients": [{"name": "Carne moída", "quantity": 500, "unit": "g"}, {"name": "Mandioca", "quantity": 1, "unit": "kg"}]}}}
MENU = json.dumps({"result": {"menu_copy": {"title": "Escondidinho da Dona Maria",
                                            "description": "Carne moída temperada sob purê de mandioca gratinado."}}})


def test_the_accept_question_shows_the_recipe_she_is_accepting():
    # Live session: "Aceitar o Escondidinho de carne moída como prato do cardápio de lançamento?" and the recipe was
    # never on screen — she approved a dish she had not read.
    state = approval.Approvals()
    state.remember_request("s1", RECIPE)
    question = state.with_evidence("s1", "Aceitar o Escondidinho de carne moída como prato do cardápio de lançamento?")
    assert "Carne moída 500 g" in question and "Mandioca 1 kg" in question and "8 porções" in question
    assert question.startswith("Aceitar")


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
