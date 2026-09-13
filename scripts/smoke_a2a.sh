#!/usr/bin/env bash
# A2A edge smoke test (PLAN.md D3): allowed edges pass authentication and the trust list,
# every other caller is rejected. Probes run from inside the compose network (fifi container).
#
# TODO(open question 4): Hermes serves Agent Cards publicly, so authentication is asserted on
# JSON-RPC POSTs (GetTask for a nonexistent task: passes auth/trust checks without starting an
# agent turn) instead of on the card GET the plan describes.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

probe() {  # probe <service> <token|""> -> HTTP status of an authenticated JSON-RPC call
  docker compose exec -T -e PROBE_URL="http://$1:9900/" -e PROBE_TOKEN="$2" fifi /opt/hermes/.venv/bin/python - <<'EOF'
import json, os, urllib.error, urllib.request
body = json.dumps({"jsonrpc": "2.0", "id": "smoke", "method": "GetTask", "params": {"id": "smoke-nonexistent"}}).encode()
headers = {"Content-Type": "application/json", "A2A-Version": "1.0"}
if os.environ["PROBE_TOKEN"]:
    headers["Authorization"] = "Bearer " + os.environ["PROBE_TOKEN"]
request = urllib.request.Request(os.environ["PROBE_URL"], data=body, headers=headers, method="POST")
try:
    with urllib.request.urlopen(request, timeout=10) as response:
        print(response.status)
except urllib.error.HTTPError as error:
    print(error.code)
EOF
}

card() {  # card <service> -> HTTP status of the public Agent Card
  docker compose exec -T -e PROBE_URL="http://$1:9900/.well-known/agent-card.json" fifi /opt/hermes/.venv/bin/python -c \
    'import os, urllib.request; print(urllib.request.urlopen(os.environ["PROBE_URL"], timeout=10).status)'
}

failures=0
expect() {  # expect <label> <got> <allowed statuses...>
  local label=$1 got=$2; shift 2
  for status in "$@"; do
    if [ "$got" = "$status" ]; then echo "ok    $label ($got)"; return; fi
  done
  echo "FAIL  $label: got $got, expected one of: $*"; failures=$((failures + 1))
}

for service in recipe-expert cost-expert marketing-expert researcher; do
  expect "card $service is served" "$(card "$service")" 200
  expect "no token -> $service" "$(probe "$service" "")" 401
  expect "wrong token -> $service" "$(probe "$service" "not-a-valid-token")" 401
done

expect "fifi -> recipe-expert" "$(probe recipe-expert "$A2A_TOKEN_FIFI")" 200
expect "fifi -> cost-expert" "$(probe cost-expert "$A2A_TOKEN_FIFI")" 200
expect "fifi -> marketing-expert" "$(probe marketing-expert "$A2A_TOKEN_FIFI")" 200
expect "recipe-expert -> researcher" "$(probe researcher "$A2A_TOKEN_RECIPE_EXPERT")" 200
expect "cost-expert -> researcher" "$(probe researcher "$A2A_TOKEN_COST_EXPERT")" 200
expect "marketing-expert -> researcher" "$(probe researcher "$A2A_TOKEN_MARKETING_EXPERT")" 200

expect "fifi -> researcher rejected" "$(probe researcher "$A2A_TOKEN_FIFI")" 401 403
expect "recipe-expert -> cost-expert rejected" "$(probe cost-expert "$A2A_TOKEN_RECIPE_EXPERT")" 401 403
expect "cost-expert -> marketing-expert rejected" "$(probe marketing-expert "$A2A_TOKEN_COST_EXPERT")" 401 403

[ "$failures" -eq 0 ] && echo "A2A smoke: all edges as expected" || { echo "A2A smoke: $failures failure(s)"; exit 1; }
