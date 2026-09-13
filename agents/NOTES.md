# Agents — implementation notes

## Hermes image pin (PLAN.md D1)
- Official image `nousresearch/hermes-agent:v2026.9.11`, digest
  `sha256:9469b3e78b9545b6d576eb8887a95352e9a0ea83730eaf31431cf862ca1010e1`.
- Release tags are date-based (`vYYYY.M.D`); there is no `0.21.2` tag. `v2026.9.11` contains
  `/opt/hermes/pyproject.toml` with `version = "0.21.2"` — the version the plan's Hermes facts were
  verified against — so no fallback clone was needed.
- Image layout: code in `/opt/hermes`, venv `/opt/hermes/.venv` (Python 3.13.5), `HERMES_HOME=/opt/data`,
  entrypoint `/opt/hermes/docker/entrypoint-dispatch.sh` (s6-overlay) → `main-wrapper.sh`, which execs an
  executable first argument directly (as user `hermes`) or runs `hermes <args>`.
- Bundled Python packages used by our plugins: `jsonschema` 4.26.0, `anthropic` 0.87.0. `pytest` is not
  bundled and is installed by `agents/Dockerfile`.

## Facts re-verified in the pinned image
- Classic CLI: `hermes --cli` forces the prompt_toolkit REPL (`display.interface: cli` is also the default).
- Model config: `model.default` + `model.provider`; provider `anthropic` has aliases `claude`,
  `claude-oauth`, `claude-code` and reads `CLAUDE_CODE_OAUTH_TOKEN` (PLAN.md D46, Hermes fact 19).
- Plugins are opt-in via `plugins.enabled`; manifest keys: `name`, `version`, `description`, `author`,
  `requires_env`, `provides_tools`, `provides_hooks`, `hooks`.
- `ctx.register_tool(name, toolset, schema, handler, ...)`; handlers are called as `handler(args, **kwargs)`
  and return a string; `schema` is `{name, description, parameters}`.
- MCP servers over HTTP: `mcp_servers.<name>.url` + `headers`.
- Web backend selection: `web.backend` / `web.search_backend` / `web.extract_backend` (`tavily` with
  `TAVILY_API_KEY`).
- A2A server: `A2A_PORT`, `A2A_HOST`, `A2A_PUBLIC_URL`, `A2A_PEER_TOKENS="name:token"`, `A2A_TRUSTED_PEERS`
  (env or `a2a.trusted_peers`). Agent Cards are served publicly; JSON-RPC POSTs are authenticated
  (401) and checked against the trust list (403). The gateway authorizes platform users through
  `A2A_ALLOWED_USERS` (fail closed without it), so each server lists its allowed callers there too.
- Toolset names include `terminal`, `file`, `code_execution`, `browser`, `computer_use`, `web`,
  `delegation`, `memory`, `clarify`, `skills`.
