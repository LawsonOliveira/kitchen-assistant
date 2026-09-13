"""Requirement-extraction eval (PLAN.md Loop 2 step 6, D26): recipe_search on fixture pages vs hand labels.

Runs on the host against the researcher-eval service (compose profile `eval`), which replays
evals/web_fixtures/pages through its normal web tools (evals/NOTES.md). Prints one line per page and the
recall per category, and exits non-zero below the thresholds: equipment 100%, techniques and operations >= 90%.
"""

import json
import os
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins"))
from kitchen_a2a.validation import call_with_contract  # noqa: E402

PEER_URL = f"http://127.0.0.1:{os.environ.get('RESEARCHER_EVAL_HOST_PORT', '59900')}/"
FIXTURE_BASE_URL = "https://fixtures.kitchen.test/"
PAGES = ROOT / "evals" / "web_fixtures" / "pages"
THRESHOLDS = {"equipment": 1.0, "techniques": 0.9, "operations": 0.9}
OPERATION_KEYS = ("stove_burners>=", "max_batch_time_minutes>=", "fridge_space_liters>=")
BATCH_SIZE = 5  # recipe_search accepts at most 5 items per request


def category(requirement: str) -> str:
    if requirement.startswith("technique:"):
        return "techniques"
    if requirement.startswith(OPERATION_KEYS):
        return "operations"
    return "free_text" if ":" in requirement else "equipment"


def env_value(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    for line in (ROOT / ".env").read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == name and value.strip():
            return value.strip().strip("\"'")
    raise SystemExit(f"{name} is not set in the environment or .env")


def page_title(page: str) -> str:
    title = re.search(r"<title>([^<]*)</title>", (PAGES / page).read_text(encoding="utf-8")).group(1)
    return title.split(" — ")[0]


def extracted_recipes(rows: list[dict], token: str) -> dict[str, dict]:
    """page file name -> recipe researcher returned for it (only recipes whose fixture URL was visited)."""
    recipes = {}
    for start in range(0, len(rows), BATCH_SIZE):
        request = {"task_type": "recipe_search",
                   "trace": {"trace_id": f"eval-requirements-{uuid.uuid4().hex[:12]}", "parent_span_id": None,
                             "turn_cost_remaining_usd": 5.0},
                   "items": [page_title(row["page"]) for row in rows[start:start + BATCH_SIZE]]}
        reply = call_with_contract(PEER_URL, token, request, ROOT / "contracts/research/recipe_search.response.json", timeout_s=270)
        if "error" in reply:
            raise SystemExit(f"researcher-eval error: {json.dumps(reply['error'], ensure_ascii=False)}")
        for recipe in reply["results"]:
            recipes[recipe["source_url"].removeprefix(FIXTURE_BASE_URL)] = recipe
        if reply["unverified_source"]:
            print("unverified sources:", reply["unverified_source"])
    return recipes


def main() -> int:
    rows = [json.loads(line) for line in (ROOT / "evals/requirements_extraction.jsonl").read_text().splitlines() if line.strip()]
    recipes = extracted_recipes(rows, env_value("A2A_TOKEN_RECIPE_EXPERT"))
    expected_count = {name: 0 for name in THRESHOLDS}
    found_count = {name: 0 for name in THRESHOLDS}
    for row in rows:
        recipe = recipes.get(row["page"])
        extracted = set(recipe["requirements"]) if recipe else set()
        for requirement in row["expected_requirements"]:
            expected_count[category(requirement)] += 1
            found_count[category(requirement)] += requirement in extracted
        status = "ok  " if recipe and set(row["expected_requirements"]) <= extracted else "MISS"
        print(f"{status} {row['page']}: expected {row['expected_requirements']}, "
              f"extracted {sorted(extracted) if recipe else 'no recipe'}, "
              f"extra {sorted(extracted - set(row['expected_requirements']))}, "
              f"prep {recipe['prep_time_minutes'] if recipe else None}/{row['expected_prep_time_minutes']} min")
    failed = False
    for name, threshold in THRESHOLDS.items():
        recall = found_count[name] / expected_count[name] if expected_count[name] else 1.0
        print(f"{name}: recall {recall:.0%} ({found_count[name]}/{expected_count[name]}), threshold {threshold:.0%} "
              f"— {'pass' if recall >= threshold else 'FAIL'}")
        failed = failed or recall < threshold
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
