#!/usr/bin/env bash
# Secret scan (PLAN.md Loop 8 Tests): real key formats in tracked files, and .env ignored. The plan's first pattern
# (bare "pk-lf-|sk-lf-") also matched documentation and test doubles, so the prefixes require a real-length suffix.
set -euo pipefail
cd "$(dirname "$0")/.."
PATTERN='sk-ant-[A-Za-z0-9_-]{20,}|pk-lf-[0-9a-f]{16,}|sk-lf-[0-9a-f]{16,}|[0-9]{8,10}:[A-Za-z0-9_-]{35}'
if git grep -nIE "$PATTERN" -- . ':!*.lock'; then
  echo "secret scan: possible secrets above" >&2
  exit 1
fi
git check-ignore -q .env || { echo "secret scan: .env is not ignored" >&2; exit 1; }
echo "secret scan: no real key formats in tracked files; .env is ignored"
