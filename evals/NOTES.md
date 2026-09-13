# Evals — notes

## Loop 2 step 6 spike: how researcher reaches the fixture pages

Question: can researcher, in eval mode, read `evals/web_fixtures/pages/*.html` through its normal
`web_search` / `web_extract` tools, so the requirement-extraction eval measures the real child prompt and
schema on known pages?

Preferred option (PLAN.md): a `web-fixtures` container serving the pages plus a SearXNG-compatible
`/search?format=json`, with researcher started with `SEARXNG_URL`.

Findings in the pinned image (`nousresearch/hermes-agent:v2026.9.11`):

- `plugins/web/searxng/provider.py` is **search-only** ("SearXNG aggregates upstream engines but does not
  fetch URLs"). It would find a fixture page, but it cannot extract it.
- Every extract-capable provider is a remote service: `exa`, `tavily`, `parallel`, `firecrawl`, `keenable`,
  `perplexity` (`grep "def extract" plugins/web`). None of them can reach a container on the compose network.
- `web_extract` also drops private-network URLs before any backend (`tools/url_safety.py`), unless
  `HERMES_ALLOW_PRIVATE_URLS` / `security.allow_private_urls` weakens that protection.
- A `pre_tool_call` `block` cannot serve fixture data either: its message reaches the model wrapped as a tool
  error (`tool_error(block_message)` in `model_tools.py`).
- `transform_tool_result` replaces the final result string of a tool (first string wins) and receives the
  tool arguments, and it fires for the web children that run inside `fan_out_research` (unlike
  `post_tool_call`, see PLAN.md C18).

Decision: the fallback. With `SABOR_WEB_FIXTURES_DIR` set, researcher's `transform_tool_result` replays
`web_search` (fixture pages ranked by title words) and `web_extract` (visible text of fixture pages at
`https://fixtures.sabor.test/<page>`) and records those URLs as visited, so the provenance filter behaves as
in production. Only the `researcher-eval` service (compose profile `eval`) sets the variable, and it gets an
invalid Tavily key, so the real tool call fails without spending credits before the replay replaces it. No
`web-fixtures` container, server or Dockerfile is needed (recorded as PLAN.md correction C27).

## Loop 3 manual scenario runs (2026-09-13)

Each scenario was run once in the classic CLI (`hermes --cli` in the fifi container, driven through a pty with real
`clarify` clicks), from a reset state (business tables truncated, spreadsheet re-seeded, fifi memory cleared), with
the owner's answers taken from the scenario's facts. `expected_state` was checked with read-only SQL; the
trajectory was read from `audit_log` and fifi's session.

| Scenario | Result | Notes (corrections in PLAN.md) |
|---|---|---|
| 01_happy_path | pass | pantry-only recipe dictated by the owner; accepted and priced after clicks; launch menu shown. CMV R$ 12,92 → R$ 3,23/portion → R$ 9,90 / 10,90 / 13,90 checked by hand |
| 02_oven_not_mentioned | pass (3rd attempt) | 1st: "óleo a gosto" density question and quotes without package (C32, C33); 2nd: web estimate replaced the spreadsheet chicken price, network outage (C34, C35); 3rd: oven recorded before the four purchases, accept and price |
| 03_missing_item_price_corrected | pass | web estimate stored, owner's R$ 3,49 as owner_confirmed, CMV recomputed with it (R$ 14,07) |
| 04_budget_exceeded_then_raised | pass | R$ 130,00 vs R$ 80,00, alternatives offered, +R$ 50,00 after a click, purchases after the raise |
| 05_shared_tomato_stock | pass | sauce reserved 2000 g; vinaigrette bought one 2 kg package; own reservation counted as missing (C36) |
| 06_chocolate_topping_weight | pass | owner's "1 unit = 1000 g" stored; rule changed to evidence_from_owner (test commit); CMV R$ 50,84 |
| 07_marketing_promotion_simulated | pass | reference dish R$ 7,90 / 9,90 / 10,90 with the pricing-explanation steps; copy saved and 15% promotion simulated then registered after clicks |
| 08_pantry_import_diff | pass | preview showed only Tomate R$ 16,00 → R$ 20,00; applied after a click |
| 09_non_linear_changes_mind | pass (4th attempt) | rejections of unregistered candidates were not recorded (C38); an outage cut the 3rd attempt; the 4th recorded the rejection, excluded it from the next round and showed no prices before constraints |

Permissions: every write in `audit_log` came from the agent the MCP permission table allows (enforced by costs-mcp
tokens); every click-required write was preceded in fifi's session by `clarify` answered "Confirmar". One deviation
(custom confirmation wording, scenario 02 first attempt) is addressed by C33 and open question 10 (Loop 4).
