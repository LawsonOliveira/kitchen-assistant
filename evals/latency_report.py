"""Where a turn's time goes (PLAN.md C76). Reads the events the stack already emits (kitchen_observability, D32) plus
costs-mcp's audit_log, and prints one line per call type with p50/p90, how often independent expert calls really overlap,
and the recipe cache's hit rate.

    make latency-report SINCE="2026-09-14T10:00:00+00:00"

The helpers are unit-tested; main() reads the live cockpit and database.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone

CALL_KINDS = ("llm_call", "a2a_call", "tool_call", "mcp_call", "subagent")


def percentile(values: list[float], share: float) -> float:
    """The value at `share` of the sorted measurements (nearest rank, as small samples deserve)."""
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(share * len(ordered)) - 1) if share < 1 else len(ordered) - 1)
    return ordered[index]


def summarize(events: list[dict]) -> list[dict]:
    """One row per agent and call name, slowest p90 first."""
    durations: dict[tuple[str, str, str], list[float]] = {}
    for event in events:
        if event.get("kind") in CALL_KINDS and event.get("duration_ms") is not None:
            durations.setdefault((event.get("agent", "?"), event["kind"], event.get("name") or "?"), []).append(event["duration_ms"] / 1000)
    rows = [{"agent": agent, "kind": kind, "name": name, "count": len(values),
             "p50_s": round(percentile(values, 0.5), 1), "p90_s": round(percentile(values, 0.9), 1),
             "max_s": round(max(values), 1), "total_s": round(sum(values), 1)}
            for (agent, kind, name), values in durations.items()]
    return sorted(rows, key=lambda row: row["p90_s"], reverse=True)


def _at(event: dict) -> datetime:
    return datetime.fromisoformat(event["started_at"])


def parallel_share(events: list[dict]) -> float:
    """Share of the orchestrator's expert calls that overlap another one: the prompt asks for independent requests in
    the same reply, and only the events say whether that happens."""
    calls = sorted([event for event in events if event.get("kind") == "a2a_call" and event.get("duration_ms") is not None], key=_at)
    if len(calls) < 2:
        return 0.0
    overlapping = set()
    for index, call in enumerate(calls):
        ends = _at(call) + timedelta(milliseconds=call["duration_ms"])
        for other in calls[index + 1:]:
            if _at(other) < ends:
                overlapping |= {index, calls.index(other)}
    return round(len(overlapping) / len(calls), 2)


def cache_hit_rate(audit: list[dict]) -> tuple[int, int]:
    """(lookups that found a recipe, lookups) for find_cached_recipes in the audit log."""
    hits = lookups = 0
    for row in audit:
        if row.get("tool") != "find_cached_recipes":
            continue
        result = row.get("result")
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except ValueError:
                result = {}
        lookups += 1
        hits += bool((result or {}).get("recipes"))
    return hits, lookups


def report(events: list[dict], audit: list[dict]) -> str:
    rows = summarize(events)
    hits, lookups = cache_hit_rate(audit)
    lines = ["# Latency report", "", "| Agent | Kind | Call | Count | p50 (s) | p90 (s) | max (s) | total (s) |",
             "|---|---|---|---|---|---|---|---|"]
    lines += [f"| {row['agent']} | {row['kind']} | {row['name']} | {row['count']} | {row['p50_s']} | {row['p90_s']} "
              f"| {row['max_s']} | {row['total_s']} |" for row in rows]
    lines += ["", f"- expert calls overlapping another one: {parallel_share(events):.0%}",
              f"- recipe cache: {hits} hit(s) in {lookups} lookup(s)"]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    import trials

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", default=(datetime.now(timezone.utc) - timedelta(hours=6)).isoformat(timespec="milliseconds"),
                        help="ISO timestamp; defaults to six hours ago")
    args = parser.parse_args(argv)
    print(report(trials.events_since(args.since), trials.audit_log()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
