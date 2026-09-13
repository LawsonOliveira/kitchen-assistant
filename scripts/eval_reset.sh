#!/usr/bin/env bash
# Business-state reset before each eval trial (PLAN.md Loop 6 step 4). It erases the RUNNING stack's data, so it
# refuses unless SABOR_ALLOW_EVAL_RESET=1 is set, and says what it would erase.
set -euo pipefail
cd "$(dirname "$0")/.."

TABLES="audit_log, pantry_imports, promotions, menu_copy, dish_reservations, purchases, dish_requirements, dishes, budget_adjustments, kitchen_profile, conversion_factors, ingredient_prices, pantry_stock, ingredients"
AGENTS="fifi recipe-expert cost-expert marketing-expert researcher"

if [ "${SABOR_ALLOW_EVAL_RESET:-}" != "1" ]; then
  cat >&2 <<MSG
eval-reset erases the business state of the running stack:
  - app Postgres tables: $TABLES
    (costs-mcp re-seeds data/despensa_dona_maria.xlsx when it restarts)
  - fifi memories (/opt/data/memories) and received documents (/opt/data/cache/documents)
Refusing to run: set SABOR_ALLOW_EVAL_RESET=1 to confirm.
MSG
  exit 2
fi

docker compose exec -T postgres psql -U sabor -d sabor -q -c "TRUNCATE $TABLES RESTART IDENTITY CASCADE"
docker compose exec -T -u hermes fifi sh -c 'rm -f /opt/data/memories/* /opt/data/cache/documents/*'
docker compose restart costs-mcp >/dev/null
docker compose up -d --wait costs-mcp >/dev/null
# shellcheck disable=SC2086
docker compose restart $AGENTS >/dev/null
# shellcheck disable=SC2086
docker compose up -d --wait $AGENTS >/dev/null
docker compose exec -T postgres psql -U sabor -d sabor -At -c "SELECT 'ingredients=' || count(*) FROM ingredients; SELECT 'budget_remaining=' || remaining FROM budget_status"
