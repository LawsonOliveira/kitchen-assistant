"""The guard classifier through Hermes' plugin LLM (PLAN.md C39): a verdict is never lost to a cosmetic field."""

import json

import jsonschema

from kitchen_guardrails import classifier


class SchemaCheckingLlm:
    """Like agent.plugin_llm.PluginLlm: the model's JSON is validated against the json_schema it was given."""

    def __init__(self, reply: dict):
        self.reply = reply

    def complete_structured(self, *, json_schema, **_):
        jsonschema.validate(self.reply, json_schema)  # PluginLlm raises ValueError here, which becomes GuardInfraError

        class Result:
            parsed, text = self.reply, json.dumps(self.reply)
        return Result()


def test_a_long_category_or_reason_still_gives_the_verdict_truncated():
    # Live: Haiku answered category "cost calculation and purchase confirmation" (42 characters); the schema's
    # maxLength 40 made the plugin LLM reject the reply, and Dona Sálvia answered with the infrastructure message.
    reply = {"verdict": "allow", "category": "cost calculation and purchase confirmation", "reason": "x" * 400}
    verdict = classifier.classify(SchemaCheckingLlm(reply), "output_policy.md", "Oi, Dona Maria!", 10)
    assert verdict.verdict == "allow" and verdict.category == reply["category"][:40] and verdict.reason == "x" * 300


def test_the_schema_still_requires_a_known_verdict():
    reply = {"verdict": "maybe", "category": "x", "reason": "y"}
    try:
        classifier.classify(SchemaCheckingLlm(reply), "output_policy.md", "Oi", 10)
    except classifier.GuardInfraError:
        return
    raise AssertionError("an unknown verdict must raise GuardInfraError")
