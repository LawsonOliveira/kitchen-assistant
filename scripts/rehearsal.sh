#!/usr/bin/env bash
# Fresh-clone rehearsal (PLAN.md Loop 8): only what is committed plus the local .env. It recreates the `sabor` compose
# project from a temporary clone, runs the self-test and every eval layer (which erases business state), copies the
# eval report back and finally recreates the stack from this checkout again. Exits non-zero on any failure.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
export PATH="$HOME/.local/bin:$PATH"

restore() {
  mkdir -p "$REPO/evals/results"
  cp -R "$WORK/sabor/evals/results/." "$REPO/evals/results/" 2>/dev/null || true
  (cd "$REPO" && make up >/dev/null) || echo "rehearsal: could not recreate the stack from $REPO" >&2
  rm -rf "$WORK"
}
trap restore EXIT

git clone --quiet "$REPO" "$WORK/sabor"
cp "$REPO/.env" "$WORK/sabor/.env"
cd "$WORK/sabor"
make up
make selftest
SABOR_ALLOW_EVAL_RESET=1 make evals
echo "rehearsal: fresh clone → make up → make selftest → make evals passed"
