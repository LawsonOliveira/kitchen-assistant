#!/usr/bin/env bash
# Fresh-clone rehearsal (PLAN.md Loop 8): only what is committed plus the local .env. It recreates the `kitchen-assistant`
# compose project from a temporary clone, runs the self-test and the deterministic suites, and finally recreates the
# stack from this checkout again. Exits non-zero on any failure.
#
# The LLM layers of `make evals` are not run here (owner, 2026-09-15): a complete run takes about six hours and the
# entry's numbers come from the run this repository ships, evals/results/<timestamp>-final. What the rehearsal proves
# is that a fresh clone plus .env builds, comes up healthy, blocks the guard canary and passes every test that does
# not spend a model call.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
export PATH="$HOME/.local/bin:$PATH"

restore() {
  (cd "$REPO" && make up >/dev/null) || echo "rehearsal: could not recreate the stack from $REPO" >&2
  rm -rf "$WORK"
}
trap restore EXIT

git clone --quiet "$REPO" "$WORK/kitchen-assistant"
cp "$REPO/.env" "$WORK/kitchen-assistant/.env"
cd "$WORK/kitchen-assistant"
make up
make selftest
make test
make test-plugins
make test-contracts
make test-integration
echo "rehearsal: fresh clone → make up → make selftest → test, test-plugins, test-contracts, test-integration passed"
