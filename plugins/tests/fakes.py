"""Test doubles shared by the guardrail tests."""

from kitchen_guardrails.classifier import Verdict


class FakeClassifier:
    """Returns a fixed verdict ("allow" | "block" | "uncertain") or raises the given exception; records inputs."""

    def __init__(self, outcome, category="test"):
        self.outcome, self.category, self.calls = outcome, category, []

    def __call__(self, content: str) -> Verdict:
        self.calls.append(content)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return Verdict(self.outcome, self.category, "fake classifier")
