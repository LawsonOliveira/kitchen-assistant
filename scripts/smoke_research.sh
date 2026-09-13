#!/usr/bin/env bash
# Live smoke of researcher (PLAN.md Loop 2): real Tavily + model calls through the A2A contract.
# Pass criteria: recipe_search returns >= 1 schema-valid recipe (URLs already provenance-filtered) and
# ingredient_price returns >= 1 schema-valid result with a source_url.
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose exec -T recipe-expert /opt/hermes/.venv/bin/python - <<'EOF'
import json, os, sys
sys.path.insert(0, "/opt/kitchen/plugins")
from pathlib import Path
from kitchen_a2a.validation import call_with_contract

contracts = Path("/opt/kitchen/contracts/research")
trace = {"trace_id": "smoke-research", "parent_span_id": "smoke", "turn_cost_remaining_usd": 5.0}
failures = 0
for task_type, item in [("recipe_search", "frango com arroz"), ("ingredient_price", "creme de leite 200 g")]:
    request = {"task_type": task_type, "trace": trace, "items": [item]}
    reply = call_with_contract("http://researcher:9900/", os.environ["KITCHEN_A2A_TOKEN"], request,
                               contracts / f"{task_type}.response.json", timeout_s=270)
    ok = "error" not in reply and len(reply["results"]) >= 1 and all(r["source_url"].startswith("http") for r in reply["results"])
    print(("ok   " if ok else "FAIL ") + task_type, json.dumps(reply, ensure_ascii=False)[:300])
    failures += not ok
sys.exit(1 if failures else 0)
EOF
