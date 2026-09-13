# Cockpit and Langfuse stack — notes (PLAN.md Loop 5)

## Cockpit server

- Standard library only (`ThreadingHTTPServer`), port 8080: `POST /events` (bearer `SABOR_COCKPIT_TOKEN`),
  `GET /stream` (SSE: replays the ring buffer of the last 500 events, then live, keepalive every 15 s), `GET /` (the
  page), `GET /health` (compose healthcheck). Nothing is persisted.
- **Contract check by hand, not `jsonschema`.** The event contract uses six keywords (`type`, `enum`, `minLength`,
  `maxLength`, `minimum`, `pattern`) on flat properties with `additionalProperties: false`; a 20-line check keeps the
  image dependency-free (D34). It reads `contracts/events.schema.json` (mounted read-only) and refuses to start if
  the contract gains a keyword it does not check. The tests post every `events__*` fixture of
  `contracts/tests/fixtures` (valid → 202, invalid → 400), the same fixtures `jsonschema` validates in
  `contracts/tests`. Rejected: `jsonschema` (a virtualenv and a dependency for a flat schema).
- The page is one HTML file with vanilla JS: SVG pipeline `guard_input → fifi → experts → researcher → MCP →
  guard_output` (the layout lives in the `data-node` elements), the active node pulses for 2.5 s after each event and
  the edge of an A2A call, a `research` call or an `mcp__costs__*` tool call is animated; turn summary (events, model
  calls, tokens, US$, duration) for fifi's latest trace; timeline with duration, tokens and cost (last 200 rows);
  badges for the event stream, Langfuse and guardrail health events.
- **State panel from `state_snapshot.preview`.** The event contract has no payload field and caps `preview` at 200
  characters, so costs-mcp writes one line — `Saldo R$ 55,00 | #1 Arroz com frango: accepted R$ 9,90 | …` — and the
  panel splits it on ` | `. With many dishes the line is cut at 200 characters. Alternative if that becomes a problem:
  an optional `state` object in the event contract (a contract change, test-first).
- **Langfuse badge.** A thread probes `SABOR_LANGFUSE_URL/api/public/health` every 15 s and publishes a `health`
  event (`trace_id: "cockpit-health"`, agent `cockpit`) only when the status changes.
- costs-mcp calls made without a trace id are published with `trace_id: "untraced"` (the contract requires one).

## Langfuse v4 in docker-compose.yml

Source: the official `docker-compose.yml` on `langfuse/langfuse` main, read 2026-09-13.

| Service | Image (pinned) | Why this pin |
|---|---|---|
| `langfuse-web` | `langfuse/langfuse:4.35.0` | latest v4 release (2026-09-11); official compose uses the floating `:4` from docker.langfuse.com, which mirrors Docker Hub |
| `langfuse-worker` | `langfuse/langfuse-worker:4.35.0` | same release as web |
| `clickhouse` | `clickhouse/clickhouse-server:25.12.11.4` | official compose uses `25.12`; v4 needs ≥ 25.12 (26.4 recommended — kept the official line) |
| `redis` | `redis:7.4.11` | official `redis:7`; v4 needs ≥ 7.0 |
| `minio` | `cgr.dev/chainguard/minio:latest@sha256:4d397a26…eabf4c` | official image; Chainguard's free tier only publishes `:latest`, so pinned by index digest |
| `langfuse-postgres` | `postgres:17.6-alpine` | v4 needs ≥ 15; same image as the app database, already pulled |

Changes from the official file: every `CHANGEME`/default secret moved to `.env` (`LANGFUSE_NEXTAUTH_SECRET`,
`LANGFUSE_SALT`, `LANGFUSE_ENCRYPTION_KEY`, `LANGFUSE_POSTGRES_PASSWORD`, `LANGFUSE_CLICKHOUSE_PASSWORD`,
`LANGFUSE_REDIS_AUTH`, `LANGFUSE_MINIO_ROOT_PASSWORD`, plus the `LANGFUSE_INIT_*` headless init); the Postgres service
is `langfuse-postgres` (the app owns `postgres`); `TELEMETRY_ENABLED=false`; host ports only for the UI (3000) and the
MinIO media endpoint (9090), both on 127.0.0.1 (ClickHouse, Redis and the worker are not published); optional
features (AI features, Azure/OCI storage, batch exports, in-app agent, SMTP) are left at their empty defaults;
`restart: unless-stopped` like the rest of the stack. Agents get `LANGFUSE_PUBLIC_KEY/SECRET_KEY` from the headless
init keys and `LANGFUSE_BASE_URL=http://langfuse-web:3000`; nothing depends on Langfuse or the cockpit being up.

## Memory (open question 3)

- Langfuse recommends 4 cores and 16 GiB for the compose deployment. The Docker VM here has ~7.5 GiB; on 2026-09-13,
  with the app stack running (postgres, costs-mcp, five agents), `free -g` showed 4 GiB used, 1 GiB available and
  swap in use.
- Limits set (`mem_limit`): langfuse-web 1 GiB, langfuse-worker 768 MiB, clickhouse 1.5 GiB (ClickHouse sizes its
  server memory limit from the cgroup limit), langfuse-postgres 256 MiB, redis 128 MiB, minio 256 MiB, cockpit
  64 MiB — 3.97 GiB of caps.
- **Not measured**: starting containers was out of bounds while the main checkout ran live scenarios. Expectation: the
  stack fits only with little headroom next to the app, and ClickHouse migrations or the web container may hit their
  limits. Fallback per open question 3: move the six Langfuse services to `profiles: [langfuse]` (opt-in `make
  up-langfuse`), keeping the cockpit in the default stack; the agents already tolerate Langfuse being absent.
