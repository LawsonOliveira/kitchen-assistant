#!/usr/bin/env bash
# Fresh-clone rehearsal (PLAN.md Loop 8): only what is committed plus the local .env. It recreates the `kitchen-assistant` compose
# project from a temporary clone, runs the self-test and every eval layer (which erases business state), copies the
# eval report back and finally recreates the stack from this checkout again. Exits non-zero on any failure.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
export PATH="$HOME/.local/bin:$PATH"

restore() {
  mkdir -p "$REPO/evals/results"
  cp -R "$WORK/kitchen-assistant/evals/results/." "$REPO/evals/results/" 2>/dev/null || true
  (cd "$REPO" && make up >/dev/null) || echo "rehearsal: could not recreate the stack from $REPO" >&2
  rm -rf "$WORK"
}
trap restore EXIT

git clone --quiet "$REPO" "$WORK/kitchen-assistant"
cp "$REPO/.env" "$WORK/kitchen-assistant/.env"
cd "$WORK/kitchen-assistant"
make up
make selftest
KITCHEN_ALLOW_EVAL_RESET=1 make evals
echo "rehearsal: fresh clone → make up → make selftest → make evals passed"
