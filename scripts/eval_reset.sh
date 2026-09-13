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

# Agents stop first: a turn still running from an interrupted trial could write between the TRUNCATE and the seed, and
# costs-mcp only seeds an empty database. Stopping fifi also ends any CLI session left inside it.
# shellcheck disable=SC2086
docker compose stop $AGENTS >/dev/null
docker compose exec -T postgres psql -U sabor -d sabor -q -c "TRUNCATE $TABLES RESTART IDENTITY CASCADE"
docker compose run --rm --no-deps -T --entrypoint sh fifi -c 'rm -f /opt/data/memories/* /opt/data/cache/documents/*' >/dev/null
docker compose restart costs-mcp >/dev/null
docker compose up -d --wait costs-mcp >/dev/null
ingredients=$(docker compose exec -T postgres psql -U sabor -d sabor -At -c "SELECT count(*) FROM ingredients")
if ! [ "${ingredients:-0}" -gt 0 ] 2>/dev/null; then
  echo "eval-reset: the spreadsheet seed did not run (ingredients=${ingredients:-none}); agents left stopped" >&2
  exit 1
fi
# shellcheck disable=SC2086
docker compose up -d --wait $AGENTS >/dev/null
echo "eval-reset: ingredients=$ingredients, agents up"
