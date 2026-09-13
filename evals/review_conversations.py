"""PL7 path A: review Dona Maria's real conversations (PLAN.md PL7; open question 15 defaults).

Reads the orchestrator's CLI and Telegram sessions from its state.db for a date window, computes deterministic signals
(a blocked message she had to rephrase, tool errors, Cancelar clicks, turn latency, cost), scores each conversation with
the rubric judge, writes the results into Langfuse as session scores (flagged conversations also go to an annotation
queue), and writes a report plus draft proposals for a person to review. Nothing is applied automatically.
"""

import argparse
import base64
import json
import math
import os
import runpy
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

EVALS = Path(__file__).resolve().parent
REPO = EVALS.parent
_MESSAGES = runpy.run_path(str(REPO / "plugins" / "sabor_guardrails" / "messages.py"))
SCOPE_BLOCK_MESSAGE, INFRA_BLOCK_MESSAGE = _MESSAGES["SCOPE_BLOCK_MESSAGE"], _MESSAGES["INFRA_BLOCK_MESSAGE"]
REVIEWED_SOURCES = ("cli", "telegram")
LIMITS = {"latency_p90_seconds": 60, "cost_per_turn_usd": 1.00}  # open question 15 defaults
SIGNAL_SCORES = ("scope_blocks", "tool_errors", "latency_p90_seconds", "cancel_clicks")
QUEUE_NAME = "sabor-review"


def select_sessions(rows: list[dict], since: float, eval_session_ids: set[str]) -> list[str]:
    return [row["id"] for row in rows
            if row["source"] in REVIEWED_SOURCES and row["started_at"] >= since and row["id"] not in eval_session_ids]


def _json(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return None


def _error_code(data) -> str | None:
    if not isinstance(data, dict):
        return None
    error = data.get("error") or (data["result"].get("error") if isinstance(data.get("result"), dict) else None)
    return error.get("code") if isinstance(error, dict) else None


def turns(messages: list[dict]) -> list[dict]:
    """One turn per owner message: its final reply, duration, clarify answers and tool error codes."""
    result = []
    for item in messages:
        if item["role"] == "user":
            result.append({"owner": item["content"], "reply": None, "started": item["at"], "ended": item["at"],
                           "clarify_answers": [], "tool_errors": []})
        elif not result:
            continue
        elif item["role"] == "assistant" and item.get("content"):
            result[-1]["reply"], result[-1]["ended"] = item["content"], item["at"]
        elif item["role"] == "tool":
            data = _json(item.get("content"))
            if item.get("tool_name") == "clarify" and isinstance(data, dict):
                result[-1]["clarify_answers"] += [str(entry.get("user_response", "")) for entry in data.get("responses", []) if isinstance(entry, dict)]
            elif (code := _error_code(data)) is not None:
                result[-1]["tool_errors"].append(code)
    return [{**turn, "seconds": round(turn["ended"] - turn["started"], 1)} for turn in result]


def signals(conversation_turns: list[dict]) -> dict:
    blocked = [index for index, turn in enumerate(conversation_turns) if turn["reply"] == SCOPE_BLOCK_MESSAGE]
    rephrased = [conversation_turns[index]["owner"] for index in blocked
                 if index + 1 < len(conversation_turns) and conversation_turns[index + 1]["reply"] not in (None, SCOPE_BLOCK_MESSAGE)]
    latencies = sorted(turn["seconds"] for turn in conversation_turns)
    return {"turns": len(conversation_turns), "scope_blocks": len(blocked),
            "infra_blocks": sum(turn["reply"] == INFRA_BLOCK_MESSAGE for turn in conversation_turns),
            "false_positive_candidates": rephrased,
            "tool_errors": sum(len(turn["tool_errors"]) for turn in conversation_turns),
            "cancel_clicks": sum(answer.startswith("Cancelar") for turn in conversation_turns for answer in turn["clarify_answers"]),
            "latency_p90_seconds": latencies[max(0, math.ceil(0.9 * len(latencies)) - 1)] if latencies else 0}


def alerts(conversation_signals: dict, cost_usd: float, limits: dict = LIMITS) -> list[str]:
    found = []
    if conversation_signals["latency_p90_seconds"] > limits["latency_p90_seconds"]:
        found.append(f"p90 turn latency {conversation_signals['latency_p90_seconds']:g} s > {limits['latency_p90_seconds']:g} s")
    per_turn = cost_usd / conversation_signals["turns"] if conversation_signals["turns"] else 0.0
    if per_turn > limits["cost_per_turn_usd"]:
        found.append(f"cost per turn US$ {per_turn:.2f} > US$ {limits['cost_per_turn_usd']:.2f}")
    return found


def score_payloads(session_id: str, conversation_signals: dict, rubric_scores: dict) -> list[dict]:
    values = {**rubric_scores, **{name: conversation_signals[name] for name in SIGNAL_SCORES}}
    return [{"sessionId": session_id, "name": name, "value": value, "dataType": "NUMERIC", "comment": "review_conversations"}
            for name, value in values.items()]


def needs_annotation(judge: dict, conversation_signals: dict, conversation_alerts: list[str]) -> bool:
    return bool(judge.get("alert") or conversation_signals["false_positive_candidates"] or conversation_signals["tool_errors"]
                or conversation_signals["infra_blocks"] or conversation_alerts)


def guard_dataset_drafts(candidates: list[str]) -> str:
    return "\n".join(json.dumps({"message": message, "last_assistant_message": "", "expected": "allow",
                                 "category": "review_false_positive"}, ensure_ascii=False) for message in candidates)


def report(date: str, reviews: list[dict]) -> str:
    lines = [f"# Conversation review {date}", "", "| Session | Source | Turns | Scope blocks | Tool errors | Cancelar | p90 (s) | US$ | Judge mean | Alerts |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    for item in reviews:
        s = item["signals"]
        lines.append(f"| {item['session_id']} | {item['source']} | {s['turns']} | {s['scope_blocks']} | {s['tool_errors']} | {s['cancel_clicks']} "
                     f"| {s['latency_p90_seconds']:g} | {item['cost_usd']:.2f} | {item['judge'].get('mean', '—')} | {'; '.join(item['alerts']) or '—'} |")
    candidates = [(item["session_id"], message) for item in reviews for message in item["signals"]["false_positive_candidates"]]
    lines += ["", "## Messages blocked that she had to rephrase (possible guard false positives)", ""]
    lines += [f"- {session}: {message}" for session, message in candidates] or ["none"]
    return "\n".join(lines) + "\n"


# --- live run ------------------------------------------------------------------------------------------------------

SESSIONS = r'''
import json, sqlite3
db = sqlite3.connect("file:/opt/data/state.db?mode=ro", uri=True)
rows = [{"id": i, "source": s, "started_at": t, "cost_usd": c or 0.0} for i, s, t, c in
        db.execute("SELECT id, source, started_at, estimated_cost_usd FROM sessions")]
print("ROWS " + json.dumps(rows))
'''


def _eval_session_ids() -> set[str]:
    ids = set()
    for path in (EVALS / "results").glob("*/*.json"):
        try:
            session = json.loads(path.read_text()).get("session_id")
        except ValueError:
            continue
        if session:
            ids.add(session)
    return ids


def _langfuse(env: dict):
    auth = base64.b64encode(f"{env['LANGFUSE_INIT_PROJECT_PUBLIC_KEY']}:{env['LANGFUSE_INIT_PROJECT_SECRET_KEY']}".encode()).decode()
    base = f"http://127.0.0.1:{env.get('LANGFUSE_HOST_PORT') or '3000'}/api/public"

    def call(method: str, path: str, body: dict | None = None) -> dict:
        request = urllib.request.Request(f"{base}/{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read() or b"{}")

    return call


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", help="YYYY-MM-DD (default: 7 days ago)")
    parser.add_argument("--no-langfuse", action="store_true", help="write only the local report")
    parser.add_argument("--sources", default=",".join(REVIEWED_SOURCES), help="comma-separated session sources (cli,telegram)")
    args = parser.parse_args(argv)
    import graders
    import trials

    since = datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.since else datetime.now(timezone.utc) - timedelta(days=7)
    rows = json.loads(next(line for line in trials._fifi_python(SESSIONS).splitlines() if line.startswith("ROWS ")).removeprefix("ROWS "))
    sources = set(args.sources.split(","))
    selected = [session for session in select_sessions(rows, since.timestamp(), _eval_session_ids())
                if next(row for row in rows if row["id"] == session)["source"] in sources]
    by_id, rubric, judge = {row["id"]: row for row in rows}, (EVALS / "rubric.md").read_text(), trials.judge()
    env = {**trials.dotenv(), **os.environ}
    langfuse, queue_id, problems, reviews = (None if args.no_langfuse else _langfuse(env)), None, [], []
    for session_id in selected:
        conversation_turns = turns(trials.fifi_session(session_id))
        if not conversation_turns:
            continue
        conversation_signals = signals(conversation_turns)
        transcript = [entry for turn in conversation_turns for entry in
                      ({"speaker": "owner", "text": turn["owner"]}, {"speaker": "fifi", "text": turn["reply"] or ""})]
        judged = graders.grade_judge(transcript, rubric, judge)
        conversation_alerts = alerts(conversation_signals, by_id[session_id]["cost_usd"])
        reviews.append({"session_id": session_id, "source": by_id[session_id]["source"], "signals": conversation_signals, "judge": judged,
                        "alerts": conversation_alerts, "cost_usd": by_id[session_id]["cost_usd"]})
        if langfuse is None:
            continue
        try:
            for payload in score_payloads(session_id, conversation_signals, judged["scores"]):
                langfuse("POST", "scores", payload)
            if needs_annotation(judged, conversation_signals, conversation_alerts):
                if queue_id is None:
                    queues = langfuse("GET", "annotation-queues?limit=50").get("data", [])
                    queue_id = next((q["id"] for q in queues if q["name"] == QUEUE_NAME), None) or langfuse(
                        "POST", "annotation-queues", {"name": QUEUE_NAME, "description": "Conversations flagged by review_conversations", "scoreConfigIds": []})["id"]
                langfuse("POST", f"annotation-queues/{queue_id}/items", {"objectId": session_id, "objectType": "SESSION"})
        except Exception as error:  # the local report is still written
            problems.append(f"{session_id}: Langfuse {type(error).__name__}: {error}")
    date = datetime.now().strftime("%Y-%m-%d")
    text = report(date, reviews) + ("\n## Langfuse problems\n\n" + "\n".join(f"- {p}" for p in problems) + "\n" if problems else "")
    (EVALS / "reviews").mkdir(exist_ok=True)
    (EVALS / "reviews" / f"{date}.md").write_text(text)
    candidates = [message for item in reviews for message in item["signals"]["false_positive_candidates"]]
    if candidates:
        proposals = EVALS / "proposals" / date
        proposals.mkdir(parents=True, exist_ok=True)
        (proposals / "guard_dataset_rows.jsonl").write_text(guard_dataset_drafts(candidates) + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
