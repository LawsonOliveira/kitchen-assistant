"""PL7 path A: review Dona Maria's real conversations and write the results into Langfuse (owner decisions, 2026-09-13)."""

import json

import review_conversations as review

SCOPE, INFRA = review.SCOPE_BLOCK_MESSAGE, review.INFRA_BLOCK_MESSAGE


def message(at, role, content="", tool_name=None, tool_args=None):
    return {"at": at, "role": role, "content": content, "tool_name": tool_name, "tool_args": tool_args}


def clarify(at, answer):
    return message(at, "tool", json.dumps({"responses": [{"question": "Confirma?", "user_response": answer}]}), "clarify")


CONVERSATION = [
    message(0, "user", "Oi, como você está?"), message(3, "assistant", SCOPE),
    message(10, "user", "Tô bem! Quero montar um arroz com frango."), message(12, "assistant", "", "ask_recipe_expert", {"task": "suggest_dishes"}),
    message(80, "tool", json.dumps({"result": {"candidates": []}}), "ask_recipe_expert"), message(85, "assistant", "Achei três opções."),
    message(90, "user", "Quero a segunda."), message(91, "assistant", "", "clarify", {"questions": []}), clarify(95, "Cancelar"),
    message(96, "tool", json.dumps({"error": {"code": "a2a_failure", "message": "timeout"}}), "ask_cost_expert"),
    message(100, "assistant", "Tive um probleminha, vamos tentar de novo?"),
]


def test_only_her_cli_and_telegram_sessions_in_the_window_are_reviewed_and_eval_trials_are_skipped():
    rows = [{"id": "a", "source": "telegram", "started_at": 100.0}, {"id": "b", "source": "cli", "started_at": 50.0},
            {"id": "c", "source": "api_server", "started_at": 100.0}, {"id": "d", "source": "subagent", "started_at": 100.0},
            {"id": "e", "source": "cli", "started_at": 100.0}]
    assert review.select_sessions(rows, since=60.0, eval_session_ids={"e"}) == ["a"]


def test_turns_pair_each_owner_message_with_the_final_reply_and_its_duration():
    turns = review.turns(CONVERSATION)
    assert [(turn["owner"], turn["reply"], turn["seconds"]) for turn in turns] == [
        ("Oi, como você está?", SCOPE, 3), ("Tô bem! Quero montar um arroz com frango.", "Achei três opções.", 75),
        ("Quero a segunda.", "Tive um probleminha, vamos tentar de novo?", 10)]
    assert turns[2]["clarify_answers"] == ["Cancelar"] and turns[2]["tool_errors"] == ["a2a_failure"]


def test_signals_find_a_blocked_message_she_had_to_rephrase_errors_cancels_and_slow_turns():
    signals = review.signals(review.turns(CONVERSATION))
    assert signals["turns"] == 3 and signals["scope_blocks"] == 1 and signals["infra_blocks"] == 0
    assert signals["false_positive_candidates"] == ["Oi, como você está?"]
    assert signals["tool_errors"] == 1 and signals["cancel_clicks"] == 1
    assert signals["latency_p90_seconds"] == 75


def test_alerts_use_the_owner_limits():
    signals = {"turns": 4, "latency_p90_seconds": 61, "scope_blocks": 0, "infra_blocks": 0}
    assert review.alerts(signals, cost_usd=5.0) == ["p90 turn latency 61 s > 60 s", "cost per turn US$ 1.25 > US$ 1.00"]
    assert review.alerts({**signals, "latency_p90_seconds": 20}, cost_usd=1.0) == []


def test_session_scores_for_langfuse_carry_the_rubric_and_the_signals():
    payloads = review.score_payloads("sess-1", {"scope_blocks": 1, "tool_errors": 2, "latency_p90_seconds": 75, "cancel_clicks": 0},
                                     {"tone": 4, "owner_decides": 5})
    assert {"id": "review-sess-1-tone", "sessionId": "sess-1", "name": "tone", "value": 4, "dataType": "NUMERIC",
            "comment": "review_conversations"} in payloads
    assert {"id": "review-sess-1-latency_p90_seconds", "sessionId": "sess-1", "name": "latency_p90_seconds", "value": 75,
            "dataType": "NUMERIC", "comment": "review_conversations"} in payloads
    assert len(payloads) == 6


def test_a_conversation_goes_to_the_annotation_queue_when_the_judge_alerts_or_something_looks_wrong():
    assert review.needs_annotation({"alert": False}, {"false_positive_candidates": [], "tool_errors": 0, "infra_blocks": 0}, []) is False
    assert review.needs_annotation({"alert": True}, {"false_positive_candidates": [], "tool_errors": 0, "infra_blocks": 0}, []) is True
    assert review.needs_annotation({"alert": False}, {"false_positive_candidates": ["oi"], "tool_errors": 0, "infra_blocks": 0}, []) is True
    assert review.needs_annotation({"alert": False}, {"false_positive_candidates": [], "tool_errors": 0, "infra_blocks": 0}, ["slow"]) is True


def test_false_positives_become_draft_guard_dataset_rows_for_a_person_to_review():
    rows = review.guard_dataset_drafts(["Oi, como você está?"])
    assert [json.loads(line) for line in rows.splitlines()] == [
        {"message": "Oi, como você está?", "last_assistant_message": "", "expected": "allow", "category": "review_false_positive"}]


def test_the_report_names_each_conversation_its_scores_alerts_and_candidates():
    text = review.report("2026-09-13", [{"session_id": "sess-1", "source": "telegram", "signals": {"turns": 3, "scope_blocks": 1,
                          "false_positive_candidates": ["Oi, como você está?"], "tool_errors": 1, "cancel_clicks": 1,
                          "latency_p90_seconds": 75, "infra_blocks": 0}, "judge": {"scores": {"tone": 4}, "mean": 4.0, "alert": False},
                          "alerts": ["p90 turn latency 75 s > 60 s"], "cost_usd": 0.1}])
    assert "sess-1" in text and "telegram" in text and "p90 turn latency 75 s > 60 s" in text and "Oi, como você está?" in text


def test_turn_durations_are_rounded_to_a_tenth_of_a_second():
    # First live review: a Telegram turn reported "p90 turn latency 93.4229 s" (raw timestamps from state.db).
    turns = review.turns([message(0.0, "user", "oi"), message(93.4229, "assistant", "Oi, meu bem!")])
    assert turns[0]["seconds"] == 93.4 and review.alerts(review.signals(turns), cost_usd=0.1) == ["p90 turn latency 93.4 s > 60 s"]


def test_rerunning_the_review_updates_the_same_scores_instead_of_adding_copies():
    # Second live review: every score of the Telegram session existed twice. Langfuse upserts a score by its id.
    first = review.score_payloads("sess-1", {"scope_blocks": 1, "tool_errors": 0, "latency_p90_seconds": 75, "cancel_clicks": 0}, {"tone": 4})
    again = review.score_payloads("sess-1", {"scope_blocks": 0, "tool_errors": 0, "latency_p90_seconds": 70, "cancel_clicks": 0}, {"tone": 5})
    assert [payload["id"] for payload in first] == [payload["id"] for payload in again]
    assert len({payload["id"] for payload in first}) == len(first)
    assert all("sess-1" in payload["id"] for payload in first)


def test_the_rubric_scores_carry_the_queue_config_so_the_reviewer_sees_the_judge():
    # Owner (2026-09-16): a session should reach the annotation queue with the judge's notes already on it. A score only
    # shows up in the annotation form when it is written against the queue's own score config, so the rubric criteria
    # take the config id and the deterministic signals stay plain session scores.
    configs = {"tone": "cfg-tone", "owner_decides": "cfg-owner"}
    payloads = review.score_payloads("sess-1", {"scope_blocks": 1, "tool_errors": 0, "latency_p90_seconds": 75, "cancel_clicks": 0},
                                     {"tone": 4, "owner_decides": 5}, configs)
    by_name = {payload["name"]: payload for payload in payloads}
    assert by_name["tone"]["configId"] == "cfg-tone" and by_name["owner_decides"]["configId"] == "cfg-owner"
    assert "configId" not in by_name["latency_p90_seconds"]
    assert by_name["tone"]["id"] == "review-sess-1-tone"  # the same id as before: a rerun updates, never duplicates


def test_the_queue_reuses_its_configs_and_hands_them_back_for_the_scores():
    # The queue and its score configs are created on first use and reused by name afterwards; the caller needs the ids
    # to write the judge's notes against them, so the helper returns both.
    calls = []

    def langfuse(method, path, body=None):
        calls.append((method, path))
        if path.startswith("score-configs?"):
            return {"data": [{"name": "tone", "id": "cfg-tone"}]}
        if path.startswith("annotation-queues?"):
            return {"data": []}
        if path == "score-configs":
            return {"id": f"cfg-{body['name']}"}
        return {"id": "queue-1"}

    queue_id, configs = review.queue_and_configs(langfuse, ["tone", "owner_decides"])
    assert queue_id == "queue-1"
    assert configs == {"tone": "cfg-tone", "owner_decides": "cfg-owner_decides"}
    assert ("POST", "score-configs") in calls and calls.count(("POST", "score-configs")) == 1  # tone already existed
