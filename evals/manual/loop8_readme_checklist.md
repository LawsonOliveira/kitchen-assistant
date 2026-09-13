# Loop 8 README checklist

Written before the README (PLAN.md Loop 8 Tests). The README (PT-BR) passes when every box below can be ticked by
reading it. For each decision: the choice, the alternative rejected and why.

## Brief categories (desafio-senior-ai-engineer.md) — one explicit section each
- [x] Modelo (which model per agent and why)
- [x] Arquivos de contexto (SOUL.md, `.hermes.md`, child instructions)
- [x] Ferramentas / MCP (costs-mcp tools and permissions, A2A tools, web search)
- [x] Estrutura de memória (Hermes memory on orchestrator only, write guard; business state in Postgres)
- [x] Skills (which skills, when they load)

## Key decisions (PLAN.md) — decision, rejected alternative, why
- [x] D1 Hermes from the official Docker image, pinned by tag + digest
- [x] D2 Five Hermes processes over A2A
- [x] D3 Strict call tree with per-edge tokens; orchestrator never calls researcher
- [x] D4 Only orchestrator talks to the owner; experts return `questions_for_owner`
- [x] D5 researcher: fixed task types, strict schemas, stateless, provenance-checked
- [x] D6 Typed A2A tools with contract validation
- [x] D7 All money/quantity logic in costs-mcp (deterministic MCP server)
- [x] D8 Dedicated Postgres for business state
- [x] D9 Models per agent
- [x] D10 Guardrail placement (`kitchen_guardrails` plugin)
- [x] D11 Guardrail semantics
- [x] D12 Output verifier: R$ grounding + Haiku policy, no streaming
- [x] D13 Indirect injection and tool abuse
- [x] D14 Write authorization (clarify click)
- [x] D15 Memory: taste/style only, on orchestrator, write-guarded
- [x] D16 Context files
- [x] D17 Skills for on-demand procedures
- [x] D18 Versioned config seeded into a named volume
- [x] D19 Contracts as JSON Schema; one pyproject per service
- [x] D20 Per-portion CMV and CMV%-based scenarios
- [x] D21 Platform fee 10% as a parameter
- [x] D22 Packaging shown separately from CMV
- [x] D23 Units and measures
- [x] D24 Budget, stock and lifecycle rules
- [x] D25 Deterministic viability gate with a controlled vocabulary
- [x] D26 Requirement-extraction eval thresholds
- [x] D27 Prices of missing items
- [x] D28 Alerts after cost changes
- [x] D29 Research in rounds of ≤ 3 candidates
- [x] D30 Confirmations with clarify buttons
- [x] D31 Spreadsheet ingestion
- [x] D32 Observability plugin with explicit trace id in A2A contracts
- [x] D33 Langfuse v4 self-hosted, always started
- [x] D34 Cockpit container (vanilla HTML/JS/SSE)
- [x] D35 Prompts in git, in English, hashed into traces
- [x] D36 Evals: own runner + Langfuse datasets, layered graders, pass^3
- [x] D37 Per-turn cost cap US$ 5.00 across agents
- [x] D38 Nested timeouts and fixed progress messages
- [x] D39 Channels: classic CLI + Telegram with an allowlist
- [x] D40 Web search backend: Tavily
- [x] D41 Marketing scope, simulated by cost_expert first
- [x] D42 Persona and skin
- [x] D43 Build order: full topology first
- [x] D44 Test-first in every loop
- [x] D45 Publishing is manual and last
- [x] D46 Model access through Claude Code credentials

## Accepted risks (PLAN.md) — each stated with its mitigation
- [x] Input guard lets `uncertain` through
- [x] Write confirmation decided by orchestrator's LLM (plus the deterministic click check added in Loop 4)
- [x] Hermes free-text memory holds owner preferences
- [x] Langfuse stack always starts (memory requirement)
- [x] Dedicated Postgres instead of SQLite
- [x] Full topology first instead of monolith-first
- [x] Latest-price rule instead of weighted average
- [x] No guard on web content

## Other required sections
- [x] Hermes limitations found (hooks fail open; inline tools such as clarify never reach `transform_tool_result`;
      `api_call_count` starts at 1; the API server has no clarify; Hermes' `.env` overrides the container env;
      14-day uv `exclude-newer` quarantine in the image; no per-child toolsets; no cross-process trace propagation;
      CLI streaming leaks; Telegram interim messages on by default; Langfuse v4 `events_only` API)
- [x] Simplifications: latest-price rule; the owner adopts one of the 3 scenarios (no free price)
- [x] Quickstart with the required keys (`CLAUDE_CODE_OAUTH_TOKEN`, `TAVILY_API_KEY`, tokens, Langfuse secrets,
      Telegram) and the memory requirement
- [x] Security: guard semantics, fail-open vs fail-closed, accepted risks
- [x] Observability (Langfuse, cockpit) and the LGPD note (production would use sanitized capture and retention)
- [ ] Evals and results (latest report)
- [x] Architecture diagrams (Mermaid: topology and one turn)
- [x] Demo video not included in this delivery (§4 lists it, §1 and §5 call it optional)
- [x] Next steps (WhatsApp Cloud API, cloud deploy, W3C traceparent, multi-tenant Postgres, classifier on researcher
      output, LLM evals in CI, free price beyond the scenarios)

## Review runs

- 2026-09-13 (agent, README draft `a2288af`): every decision D1–D46 has its own entry (checked with a script), the
  five brief categories, the eight accepted risks with mitigations, Hermes limitations, simplifications, quickstart,
  security, observability with the LGPD note, both Mermaid diagrams, the demo-video note and next steps are present.
  Open: "Evals and results" — the section waits for the first complete `make evals` report.
