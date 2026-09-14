"""Latency report (PLAN.md C76, latency pass): where a turn's time goes, read from the events the run already emits."""

import latency_report


EVENTS = [
    {"agent": "orchestrator", "kind": "llm_call", "name": "claude-sonnet-5", "status": "ok", "duration_ms": 3000,
     "started_at": "2026-09-14T10:00:00.000+00:00"},
    {"agent": "orchestrator", "kind": "llm_call", "name": "claude-sonnet-5", "status": "ok", "duration_ms": 5000,
     "started_at": "2026-09-14T10:00:10.000+00:00"},
    {"agent": "orchestrator", "kind": "a2a_call", "name": "ask_recipe_expert", "status": "ok", "duration_ms": 120000,
     "started_at": "2026-09-14T10:01:00.000+00:00"},
    {"agent": "orchestrator", "kind": "a2a_call", "name": "ask_cost_expert", "status": "ok", "duration_ms": 40000,
     "started_at": "2026-09-14T10:01:30.000+00:00"},
    {"agent": "researcher", "kind": "tool_call", "name": "web_search", "status": "ok", "duration_ms": 2000,
     "started_at": "2026-09-14T10:01:10.000+00:00"},
]


def test_percentiles_come_from_the_measured_values():
    assert latency_report.percentile([100], 0.9) == 100
    assert latency_report.percentile([100, 200, 300, 400], 0.5) == 200
    assert latency_report.percentile([100, 200, 300, 400], 0.9) == 400


def test_each_call_type_is_summarised_by_agent_and_name():
    rows = latency_report.summarize(EVENTS)
    assert [(row["agent"], row["name"], row["count"]) for row in rows][:2] == [
        ("orchestrator", "ask_recipe_expert", 1), ("orchestrator", "ask_cost_expert", 1)]
    slowest = rows[0]
    assert slowest["p50_s"] == 120.0 and slowest["p90_s"] == 120.0
    model = next(row for row in rows if row["name"] == "claude-sonnet-5")
    assert model["count"] == 2 and model["p50_s"] == 5.0


def test_expert_calls_that_overlap_in_time_count_as_parallel():
    # PL9 lever 2: Dona Sálvia is asked to send independent expert requests in the same reply.
    assert latency_report.parallel_share(EVENTS) == 1.0  # the two ask_* calls overlap
    serial = [dict(EVENTS[2]), {**EVENTS[3], "started_at": "2026-09-14T10:05:00.000+00:00"}]
    assert latency_report.parallel_share(serial) == 0.0


def test_the_recipe_cache_hit_rate_comes_from_the_audit_log():
    audit = [{"tool": "find_cached_recipes", "result": {"recipes": []}},
             {"tool": "find_cached_recipes", "result": {"recipes": [{"name": "Arroz com frango"}]}},
             {"tool": "cache_recipes", "result": {"cached": 2}},
             {"tool": "find_cached_recipes", "result": '{"recipes": [{"name": "Frango ensopado"}]}'}]
    assert latency_report.cache_hit_rate(audit) == (2, 3)
