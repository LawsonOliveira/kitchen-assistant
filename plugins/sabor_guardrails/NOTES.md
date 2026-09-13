# sabor_guardrails — spike notes (PLAN.md Loop 4 step 2)

Verified against the pinned image `nousresearch/hermes-agent:v2026.9.11` on 2026-09-13.

## 1. Synthetic response for an `llm_execution` short-circuit

`agent/turn_api_call.py` calls `run_llm_execution_middleware(api_kwargs, _perform_api_call, …)`; the terminal call
returns the raw provider SDK object, which the Anthropic transport then validates and normalizes. A middleware that
returns without calling `next_call` must therefore return an `anthropic.types.Message`. Tested inside the fifi
container:

```python
Message(id="msg_sabor_guard", type="message", role="assistant", model="sabor-guardrails",
        content=[TextBlock(type="text", text=SCOPE_BLOCK_MESSAGE)], stop_reason="end_turn",
        stop_sequence=None, usage=Usage(input_tokens=0, output_tokens=0))
```

`AnthropicTransport.validate_response(msg)` is `True` and `normalize_response(msg)` gives `content` = the fixed
message, `finish_reason="stop"`, no tool calls: the turn ends with our text.

Middleware context keys: `request`, `next_call`, `original_request`, `task_id`, `turn_id`, `api_request_id`,
`session_id`, `platform`, `model`, `provider`, `base_url`, `api_mode`, `api_call_count`, `middleware_trace`. There is
no agent object. A callback that raises before `next_call` is skipped (fail-open), so the guard catches everything
itself.

## 2. Gateway helper agents

Only the agent turn loop reaches `llm_execution` middleware. Context compression, session titles and plugin LLM calls
(including our own classifier) go through `agent.auxiliary_client.call_llm`, which never runs it. The one other
`AIAgent` helper is the curator (`platform="curator"`), disabled by correction C9. Rule: skip when `platform` is
`subagent` or `curator`, and classify only when `api_call_count == 1` (Hermes increments the count before each
call in `agent/turn_iteration_prep.py`; the first live self-test showed that `== 0` never matches).

## 3. Usage and cost for the cap

`post_api_request` passes `response.usage` as Hermes' normalized token buckets (`input_tokens`, `output_tokens`,
`cache_read_tokens`, `cache_write_tokens`, …) and no cost. Hermes' own `estimate_usage_cost` knows Sonnet 5 but
returns `unknown` for `claude-haiku-4-5-20251001`, so the cap uses tokens × a price table in the plugin (USD per
million tokens, input/output): `claude-sonnet-5` 2.00/10.00, `claude-haiku-4-5-20251001` 1.00/5.00 (Anthropic
first-party rates as of 2026-09; cache reads/writes counted at the input rate, a conservative over-estimate).

## 4. Fixed progress messages to the CLI and Telegram

`AIAgent._emit_status(message)` prints to the CLI and forwards to the gateway's `status_callback`, which
`gateway/run_turn_runner.py` delivers to the chat (Telegram gets the plain text unless it matches Hermes'
aux/compression noise filter). The plugin reaches the running agent through
`agent.subagent_lifecycle.get_active_subagent_parent()`, the per-turn context variable Hermes binds for the turn.

## 5. Classifier model access (open question 2)

Hermes' plugin LLM client (`ctx.llm`, `agent.plugin_llm.PluginLlm`) routes through `call_llm` with the agent's own
Claude Code credentials — no separate key. Overriding the model needs
`plugins.entries.sabor_guardrails.llm: {allow_model_override: true, allowed_models: [claude-haiku-4-5-20251001]}`.
`complete_structured(..., json_schema=VERDICT_SCHEMA, model="claude-haiku-4-5-20251001", timeout=10)` returned
parsed verdicts in 2.0–4.9 s with token usage (`cost_usd=None`). This is the route open question 2's approved default
names as the fallback; the plan's `SABOR_GUARD_API_KEY` is therefore not used, and the manual "invalid key" check
becomes an invalid guard model (a model outside `allowed_models` raises `PluginLlmTrustError` → `GuardInfraError`).
