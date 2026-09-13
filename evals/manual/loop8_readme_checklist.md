# Loop 8 README checklist

Written before the README (PLAN.md Loop 8 Tests). The README (PT-BR) passes when every box below can be ticked by
reading it. For each decision: the choice, the alternative rejected and why.

## Brief categories (desafio-senior-ai-engineer.md) — one explicit section each
- [ ] Modelo (which model per agent and why)
- [ ] Arquivos de contexto (SOUL.md, `.hermes.md`, child instructions)
- [ ] Ferramentas / MCP (costs-mcp tools and permissions, A2A tools, web search)
- [ ] Estrutura de memória (Hermes memory on fifi only, write guard; business state in Postgres)
- [ ] Skills (which skills, when they load)

## Key decisions (PLAN.md) — decision, rejected alternative, why
- [ ] D1 Hermes from the official Docker image, pinned by tag + digest
- [ ] D2 Five Hermes processes over A2A
- [ ] D3 Strict call tree with per-edge tokens; fifi never calls researcher
- [ ] D4 Only fifi talks to the owner; experts return `questions_for_owner`
- [ ] D5 researcher: fixed task types, strict schemas, stateless, provenance-checked
- [ ] D6 Typed A2A tools with contract validation
- [ ] D7 All money/quantity logic in costs-mcp (deterministic MCP server)
- [ ] D8 Dedicated Postgres for business state
- [ ] D9 Models per agent
- [ ] D10 Guardrail placement (`sabor_guardrails` plugin)
- [ ] D11 Guardrail semantics
- [ ] D12 Output verifier: R$ grounding + Haiku policy, no streaming
- [ ] D13 Indirect injection and tool abuse
- [ ] D14 Write authorization (clarify click)
- [ ] D15 Memory: taste/style only, on fifi, write-guarded
- [ ] D16 Context files
- [ ] D17 Skills for on-demand procedures
- [ ] D18 Versioned config seeded into a named volume
- [ ] D19 Contracts as JSON Schema; one pyproject per service
- [ ] D20 Per-portion CMV and CMV%-based scenarios
- [ ] D21 Platform fee 10% as a parameter
- [ ] D22 Packaging shown separately from CMV
- [ ] D23 Units and measures
- [ ] D24 Budget, stock and lifecycle rules
- [ ] D25 Deterministic viability gate with a controlled vocabulary
- [ ] D26 Requirement-extraction eval thresholds
- [ ] D27 Prices of missing items
- [ ] D28 Alerts after cost changes
- [ ] D29 Research in rounds of ≤ 3 candidates
- [ ] D30 Confirmations with clarify buttons
- [ ] D31 Spreadsheet ingestion
- [ ] D32 Observability plugin with explicit trace id in A2A contracts
- [ ] D33 Langfuse v4 self-hosted, always started
- [ ] D34 Cockpit container (vanilla HTML/JS/SSE)
- [ ] D35 Prompts in git, in English, hashed into traces
- [ ] D36 Evals: own runner + Langfuse datasets, layered graders, pass^3
- [ ] D37 Per-turn cost cap US$ 5.00 across agents
- [ ] D38 Nested timeouts and fixed progress messages
- [ ] D39 Channels: classic CLI + Telegram with an allowlist
- [ ] D40 Web search backend: Tavily
- [ ] D41 Marketing scope, simulated by cost_expert first
- [ ] D42 Persona and skin
- [ ] D43 Build order: full topology first
- [ ] D44 Test-first in every loop
- [ ] D45 Publishing is manual and last
- [ ] D46 Model access through Claude Code credentials

## Accepted risks (PLAN.md) — each stated with its mitigation
- [ ] Input guard lets `uncertain` through
- [ ] Write confirmation decided by fifi's LLM (plus the deterministic click check added in Loop 4)
- [ ] Hermes free-text memory holds owner preferences
- [ ] Langfuse stack always starts (memory requirement)
- [ ] Dedicated Postgres instead of SQLite
- [ ] Full topology first instead of monolith-first
- [ ] Latest-price rule instead of weighted average
- [ ] No guard on web content

## Other required sections
- [ ] Hermes limitations found (hooks fail open; inline tools such as clarify never reach `transform_tool_result`;
      `api_call_count` starts at 1; the API server has no clarify; Hermes' `.env` overrides the container env;
      14-day uv `exclude-newer` quarantine in the image; no per-child toolsets; no cross-process trace propagation;
      CLI streaming leaks; Telegram interim messages on by default; Langfuse v4 `events_only` API)
- [ ] Simplifications: latest-price rule; the owner adopts one of the 3 scenarios (no free price)
- [ ] Quickstart with the required keys (`CLAUDE_CODE_OAUTH_TOKEN`, `TAVILY_API_KEY`, tokens, Langfuse secrets,
      Telegram) and the memory requirement
- [ ] Security: guard semantics, fail-open vs fail-closed, accepted risks
- [ ] Observability (Langfuse, cockpit) and the LGPD note (production would use sanitized capture and retention)
- [ ] Evals and results (latest report)
- [ ] Architecture diagrams (Mermaid: topology and one turn)
- [ ] Demo video not included in this delivery (§4 lists it, §1 and §5 call it optional)
- [ ] Next steps (WhatsApp Cloud API, cloud deploy, W3C traceparent, multi-tenant Postgres, classifier on researcher
      output, LLM evals in CI, free price beyond the scenarios)

## Review runs
