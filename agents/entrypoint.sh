#!/bin/sh
# Seeds the agent's versioned config (bind-mounted read-only at /seed) into its HERMES_HOME volume on
# every start, so the repo stays the source of truth and runtime data never lands in git (PLAN.md D18).
set -eu
: "${HERMES_HOME:?HERMES_HOME must be set}"
: "${SABOR_AGENT_ROLE:?SABOR_AGENT_ROLE must be set}"

cp /seed/config.yaml "$HERMES_HOME/config.yaml"
cp /seed/SOUL.md "$HERMES_HOME/SOUL.md"

for kind in skills skins; do
  [ -d "/seed/$kind" ] || continue
  mkdir -p "$HERMES_HOME/$kind"
  for item in "/seed/$kind"/*; do
    [ -e "$item" ] || continue
    rm -rf "$HERMES_HOME/$kind/$(basename "$item")"
    cp -R "$item" "$HERMES_HOME/$kind/"
  done
done

mkdir -p "$HERMES_HOME/plugins"
for plugin in /opt/sabor/plugins/sabor_*; do
  rm -rf "$HERMES_HOME/plugins/$(basename "$plugin")"
  cp -R "$plugin" "$HERMES_HOME/plugins/"
done

cp /seed/context.md /workspace/.hermes.md
cd /workspace
exec hermes "$@"
