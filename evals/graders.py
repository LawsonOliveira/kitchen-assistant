"""Graders for Loop 6 trials (PLAN.md D36): business state, trajectory rules and the judge.

Inputs are what the runner collects after a trial: audit_log rows {at, agent, tool, args, result, error_code} from the
app Postgres, orchestrator's session messages {at, role, content, tool_name, tool_args} and the trial's events. State and
trajectory decide pass/fail; the judge only raises alerts.
"""

import json
import re
from decimal import Decimal, InvalidOperation

CONFIRMAR = re.compile(r"^Confirmar(?: \(Recommended\))?$")  # the same literal click the guardrail ledger accepts


def grade_state(scenario: dict, connection) -> list[dict]:
    """Each expected_state SQL returns one boolean; everything runs in one read-only transaction, then rolls back."""
    results = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION READ ONLY")
            for item in scenario.get("expected_state", []):
                cursor.execute(item["sql"])
                row = cursor.fetchone()  # a query that selected nothing is a failed check, not a crash
                value = row[0] if row else None
                results.append({"check": item["check"], "passed": value is True, "value": value})
    finally:
        connection.rollback()
    return results


def _json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _same(expected, actual) -> bool:
    """Subset match: dicts by the expected keys, lists exactly, numbers by value whether sent as numbers or strings."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and all(key in actual and _same(value, actual[key]) for key, value in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(expected) == len(actual) and all(map(_same, expected, actual))
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected is actual
    if expected == actual:
        return True
    try:
        return Decimal(str(expected)) == Decimal(str(actual))
    except InvalidOperation:
        return False


def _matches(row: dict, matcher: dict) -> bool:
    if row["tool"] != matcher["tool"] or ("agent" in matcher and row.get("agent") != matcher["agent"]):
        return False
    if row.get("error_code") != matcher.get("error_code"):  # without error_code only successful calls match
        return False
    result = _json(row.get("result"))
    if "args" in matcher and not _same(matcher["args"], _json(row.get("args"))):
        return False
    if "result" in matcher and not _same(matcher["result"], result):
        return False
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    return matcher.get("result_text_contains", "") in text


def _normalized(text) -> str:
    return " ".join(str(text).lower().split())


def _clarify_answers(message: dict) -> list[str]:
    data = _json(message.get("content"))
    if not isinstance(data, dict):
        return []
    entries = data["responses"] if isinstance(data.get("responses"), list) else [data]
    return [str(entry.get("user_response", "")).strip() for entry in entries if isinstance(entry, dict)]


def _is_clarify(message: dict) -> bool:
    return message.get("role") == "tool" and message.get("tool_name") == "clarify"


def _precedes(rule, audit_log, events, session) -> bool:
    firsts = [row for row in audit_log if _matches(row, rule["first"])]
    thens = [row for row in audit_log if any(_matches(row, matcher) for matcher in rule["then"])]
    if rule.get("require_then") and not thens:
        return False

    def tied(first, then):
        first_args, then_args = _json(first.get("args")) or {}, _json(then.get("args")) or {}
        return all(key in first_args and key in then_args and _same(first_args[key], then_args[key]) for key in rule.get("same_args", []))

    return all(any(first["at"] < then["at"] and tied(first, then) for first in firsts) for then in thens)


def _click_before(rule, audit_log, events, session) -> bool:
    """Mirrors the guardrail click ledger: a clarify leaves one click per Confirmar answer (replacing unused ones)
    and each click-required write spends one."""
    writes = [row for row in audit_log if row["tool"] in rule["tools"] and not row.get("error_code")
              and ("args" not in rule or _same(rule["args"], _json(row.get("args"))))]
    clarifies = [message for message in session if _is_clarify(message)]
    # At equal times a clarify comes before the write it authorizes.
    timeline = sorted([(message["at"], 0, message) for message in clarifies] + [(row["at"], 1, row) for row in writes],
                      key=lambda item: (item[0], item[1]))
    clicks = 0
    for _, is_write, item in timeline:
        if not is_write:
            clicks = sum(1 for answer in _clarify_answers(item) if CONFIRMAR.match(answer))
        elif clicks > 0:
            clicks -= 1
        else:
            return False
    return True


def _called(rule, audit_log, events, session) -> bool:
    return any(_matches(row, rule["call"]) for row in audit_log)


def _not_called(rule, audit_log, events, session) -> bool:
    return not _called(rule, audit_log, events, session)


def _evidence_from_owner(rule, audit_log, events, session) -> bool:
    owner_texts = [_normalized(message.get("content", "")) for message in session if message.get("role") == "user"]
    owner_texts += [_normalized(answer) for message in session if _is_clarify(message) for answer in _clarify_answers(message)]
    for row in audit_log:
        if _matches(row, rule["call"]):
            evidence = _normalized((_json(row.get("args")) or {}).get("evidence", ""))
            if not evidence or not any(evidence in text for text in owner_texts):
                return False
    return True


def _rejected_dish_not_suggested_again(rule, audit_log, events, session) -> bool:
    names = {}
    for row in audit_log:
        if row["tool"] == "register_candidate_dish" and not row.get("error_code"):
            dish_id = (_json(row.get("result")) or {}).get("dish_id")
            names[str(dish_id)] = _normalized(((_json(row.get("args")) or {}).get("recipe") or {}).get("name", ""))
    for rejection in (row for row in audit_log if row["tool"] == "reject_candidate_dish" and not row.get("error_code")):
        name = names.get(str((_json(rejection.get("args")) or {}).get("dish_id")))
        if not name:
            return False  # the rejected dish's name is unknown, so the rule cannot be shown to hold
        for message in session:
            args = _json(message.get("tool_args")) or {}
            if (message.get("role") == "assistant" and message.get("tool_name") == "ask_recipe_expert"
                    and args.get("task") == "suggest_dishes" and message["at"] > rejection["at"]):
                if name not in {_normalized(item) for item in (args.get("payload") or {}).get("exclude_dish_names") or []}:
                    return False
        for row in audit_log:
            if (row["tool"] == "register_candidate_dish" and row["at"] > rejection["at"]
                    and _normalized(((_json(row.get("args")) or {}).get("recipe") or {}).get("name", "")) == name):
                return False
    return True


def _guard_blocked(rule, audit_log, events, session) -> bool:
    """The named guard blocked, or the input guard stopped the turn before that guard could run."""
    blocked = {event["kind"] for event in events if event.get("status") == "blocked"}
    return rule["guard"] in blocked or "guard_input" in blocked


RULES = {"precedes": _precedes, "click_before": _click_before, "called": _called, "not_called": _not_called,
         "evidence_from_owner": _evidence_from_owner, "guard_blocked": _guard_blocked,
         "rejected_dish_not_suggested_again": _rejected_dish_not_suggested_again}


def grade_trajectory(scenario: dict, audit_log: list, events: list, session: list) -> list[dict]:
    results = []
    for rule in scenario.get("trajectory_rules", []):
        if rule["type"] not in RULES:
            raise ValueError(f"unknown trajectory rule type {rule['type']!r} in rule {rule.get('id')!r}")
        results.append({"id": rule["id"], "type": rule["type"], "passed": RULES[rule["type"]](rule, audit_log, events, session)})
    return results


def rubric_criteria(rubric_text: str) -> list[str]:
    return re.findall(r"^## (\w+) —", rubric_text, flags=re.M)


def grade_judge(transcript: list, rubric_text: str, judge) -> dict:
    """judge(transcript, rubric_text) -> {criterion: 1..5}. Alert when the mean is below 3.5 or any criterion is ≤ 2."""
    criteria = rubric_criteria(rubric_text)
    scores = judge(transcript, rubric_text)
    if set(scores) != set(criteria) or any(isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5
                                           for score in scores.values()):
        raise ValueError(f"judge must score exactly {criteria} with integers 1–5, got {scores}")
    mean = sum(scores.values()) / len(criteria)
    return {"scores": dict(scores), "mean": mean, "alert": mean < 3.5 or min(scores.values()) <= 2}
