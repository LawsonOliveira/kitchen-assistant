"""PL8 (owner): researched recipes are cached in Postgres and reused before a new web search (PL9 latency)."""

import pytest
from conftest import ingredient, make_recipe

from costs_mcp import operations
from costs_mcp.operations import DomainError


def web_recipe(name, url, **extra):
    return {**make_recipe([ingredient("Arroz branco tipo 1", 400, "g")], name=name), "source_url": url, **extra}


def names(found):
    return [recipe["name"] for recipe in found["recipes"]]


def test_cached_recipes_are_found_by_the_words_of_the_subject_ignoring_case_and_accents(conn):
    operations.cache_recipes(conn, [web_recipe("Arroz com Frango Desfiado", "https://receitas.example/arroz-frango"),
                                    web_recipe("Bolo de Fubá Cremoso", "https://receitas.example/bolo-fuba")], "arroz com frango")
    assert names(operations.find_cached_recipes(conn, "ARROZ COM FRANGO")) == ["Arroz com Frango Desfiado"]
    assert names(operations.find_cached_recipes(conn, "bolo de fuba")) == ["Bolo de Fubá Cremoso"]
    assert names(operations.find_cached_recipes(conn, "lasanha")) == []


def test_the_same_page_is_cached_once_and_refreshed(conn):
    url = "https://receitas.example/arroz-frango"
    operations.cache_recipes(conn, [web_recipe("Arroz com frango", url, yield_portions=4)], "arroz")
    operations.cache_recipes(conn, [web_recipe("Arroz com frango", url, yield_portions=6)], "arroz")
    found = operations.find_cached_recipes(conn, "arroz com frango")["recipes"]
    assert len(found) == 1 and found[0]["yield_portions"] == 6


def test_excluded_dishes_are_not_served_and_owner_recipes_are_never_cached(conn):
    operations.cache_recipes(conn, [web_recipe("Arroz com frango", "https://receitas.example/a"),
                                    web_recipe("Arroz com frango e milho", "https://receitas.example/b")], "arroz")
    assert names(operations.find_cached_recipes(conn, "arroz com frango", exclude_dish_names=["ARROZ com frango"])) == ["Arroz com frango e milho"]
    with pytest.raises(DomainError) as error:
        operations.cache_recipes(conn, [web_recipe("Arroz da Maria", "owner")], "arroz")
    assert error.value.code == "not_a_web_recipe"


def test_an_invalid_recipe_is_refused_by_the_recipe_contract(conn):
    with pytest.raises(DomainError) as error:
        operations.cache_recipes(conn, [{"name": "sem campos"}], "arroz")
    assert error.value.code == "invalid_recipe"


def test_the_limit_caps_the_results(conn):
    operations.cache_recipes(conn, [web_recipe(f"Arroz com frango {n}", f"https://receitas.example/{n}") for n in range(5)], "arroz")
    assert len(operations.find_cached_recipes(conn, "arroz com frango", limit=3)["recipes"]) == 3
