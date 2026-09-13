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
