"""Contract fixtures: every file in fixtures/valid must validate, every file in fixtures/invalid must not.

Fixture names are `<schema key>__<case>.json`. A key without dots maps to `<key>.schema.json`
(e.g. `recipe` -> recipe.schema.json); a dotted key maps to a nested file
(e.g. `research.recipe_search.response` -> research/recipe_search.response.json).
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

CONTRACTS = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _schema_files():
    return [p for p in CONTRACTS.rglob("*.json") if "tests" not in p.relative_to(CONTRACTS).parts]


def _registry() -> Registry:
    resources = []
    for path in _schema_files():
        schema = json.loads(path.read_text())
        assert "$id" in schema, f"{path} has no $id"
        resources.append((schema["$id"], Resource.from_contents(schema)))
    return Registry().with_resources(resources)


def _schema_path(key: str) -> Path:
    if "." in key:
        return CONTRACTS / (key.replace(".", "/", 1) + ".json")
    return CONTRACTS / f"{key}.schema.json"


def _validator(key: str) -> Draft202012Validator:
    schema = json.loads(_schema_path(key).read_text())
    return Draft202012Validator(schema, registry=_registry())


def _fixtures(kind: str):
    return sorted((FIXTURES / kind).glob("*.json"))


@pytest.mark.parametrize("path", _schema_files(), ids=lambda p: str(p.relative_to(CONTRACTS)))
def test_every_contract_is_a_valid_json_schema(path):
    Draft202012Validator.check_schema(json.loads(path.read_text()))


@pytest.mark.parametrize("path", _fixtures("valid"), ids=lambda p: p.name)
def test_valid_fixture_passes(path):
    key = path.name.split("__")[0]
    errors = list(_validator(key).iter_errors(json.loads(path.read_text())))
    assert errors == [], [e.message for e in errors]


@pytest.mark.parametrize("path", _fixtures("invalid"), ids=lambda p: p.name)
def test_invalid_fixture_fails(path):
    key = path.name.split("__")[0]
    assert list(_validator(key).iter_errors(json.loads(path.read_text()))), f"{path.name} unexpectedly valid"


def test_fixture_directories_are_not_empty():
    assert _fixtures("valid") and _fixtures("invalid")
