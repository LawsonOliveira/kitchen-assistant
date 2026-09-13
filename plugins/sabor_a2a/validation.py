"""Validate A2A replies against contracts/ (PLAN.md D5, D6).

Deterministic and loud: parse JSON (models often wrap it in a markdown fence), validate against the JSON Schema,
retry once telling the peer exactly what was wrong, then return an explicit contract_violation error.
"""

import functools
import json
import os
import re
from pathlib import Path

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from .client import send_message

_BAKED_CONTRACTS = Path("/opt/sabor/contracts")
CONTRACTS_DIR = Path(os.environ.get("SABOR_CONTRACTS_DIR")
                     or (_BAKED_CONTRACTS if _BAKED_CONTRACTS.is_dir() else Path(__file__).resolve().parents[2] / "contracts"))
CONTRACTS_BASE = "https://sabor.local/contracts/"
_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


class ContractError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@functools.cache
def _documents() -> dict[str, dict]:
    documents = {}
    for path in CONTRACTS_DIR.rglob("*.json"):
        if "tests" in path.relative_to(CONTRACTS_DIR).parts:
            continue
        schema = json.loads(path.read_text())
        documents[schema["$id"]] = schema
    return documents


@functools.cache
def _validator(schema_path: str) -> Draft202012Validator:
    registry = Registry().with_resources((uri, Resource.from_contents(doc)) for uri, doc in _documents().items())
    return Draft202012Validator(json.loads(Path(schema_path).read_text()), registry=registry)


def parse_json_object(text: str) -> dict:
    candidates = []
    if match := _FENCE.search(text or ""):
        candidates.append(match.group(1))
    candidates.append((text or "").strip())
    if "{" in (text or "") and "}" in text:
        candidates.append(text[text.index("{"): text.rindex("}") + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    raise ContractError(["reply is not a JSON object"])


def validate_data(schema_path: Path | str, data: dict) -> dict:
    errors = sorted(_validator(str(schema_path)).iter_errors(data), key=str)
    if errors:
        raise ContractError([f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}" for error in errors[:10]])
    return data


def validate(schema_path: Path | str, text: str) -> dict:
    return validate_data(schema_path, parse_json_object(text))


def call_with_contract(peer_url: str, token: str, request: dict, response_schema: Path | str, timeout_s: float) -> dict:
    text = json.dumps(request, ensure_ascii=False)
    try:
        return validate(response_schema, send_message(peer_url, token, text, timeout_s))
    except ContractError as first:
        retry = (f"{text}\n\nYour previous reply did not match the JSON contract: {'; '.join(first.errors)}. "
                 "Reply again with a single JSON object only.")
        try:
            return validate(response_schema, send_message(peer_url, token, retry, timeout_s))
        except ContractError as second:
            return {"error": {"code": "contract_violation", "message": f"{peer_url} replied twice outside the contract",
                              "details": {"errors": second.errors}}}


def bundled_schema(relative_path: str, pointer: str = "") -> dict:
    """A self-contained copy of a contract (all $ref inlined) — Hermes' output_schema validator resolves no refs."""
    document = _documents()[CONTRACTS_BASE + relative_path]
    node = document
    for part in filter(None, pointer.split("/")):
        node = node[part]
    return _inline(node, document)


def _inline(node, document):
    if isinstance(node, list):
        return [_inline(item, document) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        ref = node["$ref"]
        if ref.startswith("#/"):
            target, target_document = document, document
            for part in ref[2:].split("/"):
                target = target[part]
        else:
            target_document = _documents()[ref.split("#")[0]]
            target = target_document
        return _inline(target, target_document)
    return {key: _inline(value, document) for key, value in node.items() if key not in ("$id", "$schema", "$defs")}
