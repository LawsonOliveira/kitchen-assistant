# kitchen_observability — notes (PLAN.md Loop 5)

Verified on 2026-09-13 by reading the Hermes source extracted from the local `kitchen-agent:local` image
(`nousresearch/hermes-agent:v2026.9.11`, copied with `docker create` + `docker cp`; no container was started) and by
running the Langfuse SDK on the host against a local OTLP capture server.

## Hermes facts this plugin relies on

- **Plugin module name.** Hermes imports a directory plugin as `hermes_plugins.<slug>`
  (`hermes_cli/plugins_loader.py: _directory_module_name`), not as `kitchen_observability`. A plain
  `import kitchen_observability` from another plugin would fail (plugins are not on `sys.path`) or, if it resolved,
  load a second copy with its own trace state. `__init__.py` therefore registers the loaded modules under their plain
  names in `sys.modules` (`kitchen_observability`, `.emit`, `.trace`); `test_trace.py` loads the plugin the way Hermes
  does and checks both names reach the same module. Consequence for `kitchen_guardrails`: its
  `from kitchen_observability.emit import emit` works once this plugin has loaded — list `kitchen_observability` before
  `kitchen_guardrails` in `plugins.enabled`, or import inside the hook.
- **Hook kwargs** (call sites in the image):
  - `pre_llm_call` (once per turn, `agent/turn_context.py`): `session_id, task_id, turn_id, user_message,
    conversation_history, is_first_turn, model, platform, parent_session_id, sender_id`. Not fired for agents with
    `_persist_disabled` (detached forks).
  - `post_llm_call` (`agent/turn_finalizer.py`): `session_id, task_id, turn_id, user_message, assistant_response,
    conversation_history, model, platform`.
  - `pre_api_request` / `post_api_request` (`agent/turn_api_request.py`, `agent/turn_response_intake.py`): both carry
    `task_id, turn_id, api_request_id, session_id, platform, model, provider, api_call_count`; post adds
    `api_duration, started_at, ended_at, finish_reason, response_model, response, usage` (normalized buckets
    `input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, …`, no cost).
  - `pre_tool_call`: `tool_name, args, task_id, session_id, tool_call_id, turn_id, api_request_id, middleware_trace`;
    `{"action": "modify", "args": {...}}` shallow-merges into the original args before dispatch
    (`hermes_cli/plugins.py`). MCP tools then call `session.call_tool(tool_name, arguments=args)` unchanged
    (`tools/mcp_tool_handlers.py`), so kitchen-ledger receives `trace_id`.
  - `post_tool_call`: same ids plus `result, duration_ms, status, error_type, error_message`. Fired with
    `status="blocked"` when a `pre_tool_call` blocks, and **suppressed** for tools running inside another tool.
  - `transform_tool_result`: same ids, `result, duration_ms, status, …`; fires after `post_tool_call` for every
    executed tool, including nested ones, but **not** for blocked calls. First string return replaces the result.
  - `subagent_start`: `parent_session_id, parent_turn_id, parent_subagent_id, child_session_id, child_subagent_id,
    child_role, child_goal`. `subagent_stop`: `parent_session_id, parent_turn_id, child_session_id, child_role,
    child_summary, child_status, tool_call_history, duration_ms` (no tokens), run on the caller's thread.
- **Tool handlers** receive `task_id, session_id, user_task` — no `tool_call_id`
  (`model_tools._execute_tool`). The A2A request's `parent_span_id` is therefore the latest *open* span of the calling
  tool name in that session.
- **Env denylist.** `hermes_cli/config.py` lists `LANGFUSE_PUBLIC_KEY/SECRET_KEY/BASE_URL`, but only to stop the
  dashboard from *writing* them to `.env`; values from compose reach the process.
- **Bundled `observability/langfuse` plugin** stays disabled: it is not in any `plugins.enabled` and reads
  `HERMES_LANGFUSE_*`, which compose does not set (`test_emit.py` checks every agent config).

## Design choices that differ from PLAN.md Loop 5 step 3 (proposed corrections)

- **Session-keyed trace state instead of a `ContextVar`.** Every hook and tool handler receives `session_id`, while the
  hooks, tool handlers and delegated children of one turn run on different threads, so a context variable set in
  `pre_llm_call` is not guaranteed to be visible in the tool handler that sends the A2A request. `trace.py` keeps one
  scope per session (bounded to 1,000) plus a child → parent link from `subagent_start` (same approach as
  `researcher_hooks.py`).
- **Span tree.** orchestrator has no root span: its model and tool spans are roots of the trace, and orchestrator's spans carry the
  owner's session id and the trace name through `propagate_attributes` (only orchestrator's, so spans of one trace never
  disagree on the session). A serving agent opens an `a2a_serve` span from `pre_llm_call` to `post_llm_call` under the
  caller's `parent_span_id`; a delegated child opens a `subagent` span under the tool that launched it
  (`fan_out_research`). A span's Langfuse observation id *is* the event `span_id`, which is what makes cross-process
  parenting work.
- **kitchen-ledger in Langfuse.** Loop 5 step 4 sends kitchen-ledger events to the cockpit only. In Langfuse a kitchen-ledger call
  appears as the calling agent's `mcp__ledger__<tool>` tool observation, and `audit_log.trace_id` equals the Langfuse
  trace id. Writing server-side spans from kitchen-ledger would need the SDK (plus OpenTelemetry) in that image; left out.
- **prompt_hash** = sha256 of `$HERMES_HOME/SOUL.md`, the workspace `.hermes.md`, then `skills/*/SKILL.md` in path
  order, each followed by a NUL byte. Bundled Hermes skills are synced to `skills/<category>/<name>/`
  (`tools/skills_sync.py`), so the one-level glob covers the repo's skills (plus any bundled skill at depth one) and
  stays deterministic for a pinned image.
- **Event statuses are not coerced.** `emit()` truncates `name`/`preview` to 200 characters but passes `kind` and
  `status` through; an event outside the contract is rejected by the cockpit (400) and logged once, not silently fixed.

## Langfuse Python SDK pin: `langfuse==4.15.1`

- SDK v4 is the current major; Langfuse's self-hosted compatibility matrix marks Python SDK v4 as *full support* on
  server OSS v4 (v3 SDK: deprecated). 4.15.2 was the latest on PyPI on 2026-09-13, but the Hermes image resolves packages under a 14-day uv `exclude-newer`
  quarantine (`/opt/hermes/pyproject.toml`), so the image build refused it; 4.15.1 (2026-08-28) is pinned instead.
- Its requirements (`opentelemetry-api/sdk/exporter-otlp-proto-http >=1.33.1,<2`, `httpx`, `pydantic>=2`,
  `packaging`) are already in the Hermes venv (OpenTelemetry 1.39.1, httpx 0.28.1, pydantic 2.13.4); only
  `langfuse`, `backoff` and `wrapt` are added.
- Spike on the host (`langfuse` 4.15.2, OTel 1.44):
  - `start_observation(trace_context={"trace_id", "parent_span_id"}, as_type=…)` takes ~1 ms; `.id` is the 16-hex
    OTel span id; a span created with another span's id as `parent_span_id` is exported with that parent (cross-process
    nesting works). Observation types include `generation, agent, tool, guardrail, span, event`.
  - `propagate_attributes(session_id=…, trace_name=…)` sets `session.id` and `langfuse.trace.name` on spans created
    inside it; `update(usage_details, cost_details)` exports them as `langfuse.observation.usage_details/cost_details`.
  - A span created with `trace_context` but no parent gets a random parent span id plus `langfuse.internal.as_root`;
    how the v4 UI renders those roots is a live check.
  - Base URL unreachable: 20 spans took 5 ms and `shutdown()` 0 s. The OTLP exporter logs a WARNING/ERROR per failed
    batch from its own thread — that is the SDK's logging, not ours, so it is not "once".
- `update_trace()` no longer exists in v4 (trace attributes go through `propagate_attributes`).

## For the other loops

- `from kitchen_observability.emit import emit` — e.g. `emit("guard_input", "input_guard", session_id=…,
  status="ok"|"error"|"blocked", duration_ms=…, model=…, prompt_hash=…, tokens_in=…, tokens_out=…, preview=…)`.
  `cost_usd` is computed for `llm_call` when omitted.
- `from kitchen_observability import trace`: `trace.current(session_id)` → `{"trace_id", "turn_cost_remaining_usd"
  (received in the A2A request, None on orchestrator), …}` for the cost cap. `kitchen_a2a._trace()` still sends
  `turn_cost_remaining_usd` from `KITCHEN_TURN_COST_CAP_USD` (Loop 4 step 6c replaces it).
- The price table lives in `emit.PRICES_USD_PER_MILLION` (USD per million tokens, input/output: `claude-sonnet-5`
  2.00/10.00, `claude-haiku-4-5-20251001` 1.00/5.00, cache tokens counted as input); `kitchen_guardrails` has the same
  numbers.
- Full content capture (inputs/outputs) for the demo; production would use sanitized capture and a retention period
  (LGPD) — a README note for Loop 8.

## Live checks (2026-09-13, after the merge into the main checkout)

- **Build and baseline.** The first image build refused `langfuse==4.15.2` (inside the Hermes image's 14-day uv
  `exclude-newer` quarantine); 4.15.1 is pinned. langfuse-web died five times with "JavaScript heap out of memory"
  under 1 GiB; with `NODE_OPTIONS=--max-old-space-size=1024` and a 1.5 GiB limit it settled at ~850 MiB. Memory with
  the whole stack up: clickhouse ~470 MiB, langfuse-worker ~430 MiB, agents ~220 MiB each; the Docker VM (7.5 GiB)
  runs with swap in use. Plugin and contract tests in the image: 295 passed, 1 skipped (agent configs are not baked
  into the image).
- **Langfuse v4 API.** This deployment runs in v4 `events_only` mode: `/api/public/traces/<id>` and
  `/api/public/observations` answer "not available"; `/api/public/v2/observations?traceId=<id>` works.
- **One trace across containers.** Turn "cadastra o strogonoff e me diz quanto gastaria com creme de leite":
  `audit_log.trace_id` (recipe_expert and cost_expert rows) = Langfuse trace `a98f906a…` with 50 observations:
  orchestrator GENERATIONs and TOOL `ask_recipe_expert`/`ask_cost_expert` → AGENT `recipe_expert`/`cost_expert` →
  their GENERATIONs and TOOL `mcp__ledger__*`; cost_expert TOOL `research` → AGENT `researcher` → TOOL
  `fan_out_research` → AGENT `researcher` (child) → TOOL `web_search`/`web_extract`. orchestrator's spans carry the owner's
  session id and show `isRootObservation: true` (their random OTel parent is not an observation).
- **Cockpit.** The SSE replay carried events from orchestrator, recipe_expert, cost_expert, researcher and kitchen_ledger
  (`a2a_call`, `a2a_serve`, `mcp_call`, `state_snapshot`, guard events); after a purchase confirmed in the CLI the
  latest `state_snapshot` went from "Saldo R$ 80,00" to "Saldo R$ 74,02".
- **Resilience.** With `langfuse-web` and `cockpit` stopped, a full `hermes chat -q` turn answered normally in 20 s;
  after `docker compose start` the next turn's events reached the cockpit (6) and Langfuse (5 observations).
