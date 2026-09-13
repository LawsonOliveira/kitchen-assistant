#!/bin/sh
# Seeds the agent's versioned config (bind-mounted read-only at /seed) into its HERMES_HOME volume on
# every start, so the repo stays the source of truth and runtime data never lands in git (PLAN.md D18).
set -eu
: "${HERMES_HOME:?HERMES_HOME must be set}"
: "${KITCHEN_AGENT_ROLE:?KITCHEN_AGENT_ROLE must be set}"

cp /seed/config.yaml "$HERMES_HOME/config.yaml"
# Secrets Hermes may have generated into its own .env win over the container environment (loaded with
# override=True); compose is the single source for the keys we manage, so drop Hermes' copies (PLAN.md C39).
if [ -f "$HERMES_HOME/.env" ]; then
  sed -i '/^API_SERVER_KEY=/d' "$HERMES_HOME/.env"
fi
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
for plugin in /opt/kitchen/plugins/kitchen_*; do
  rm -rf "$HERMES_HOME/plugins/$(basename "$plugin")"
  cp -R "$plugin" "$HERMES_HOME/plugins/"
done

cp /seed/context.md /workspace/.hermes.md
cd /workspace
exec hermes "$@"
