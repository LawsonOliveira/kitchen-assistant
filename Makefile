COMPOSE := docker compose
UV := uv
AGENT_PYTHON := /opt/hermes/.venv/bin/python

.PHONY: up down logs chat test test-integration test-contracts test-plugins smoke-a2a smoke-research eval-requirements import-pantry selftest test-skin eval-reset eval-guardrails evals review-conversations db-shell hermes-shell

up:
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs --no-log-prefix

# Classic prompt_toolkit CLI (--cli), as the hermes user, from the workspace that holds .hermes.md.
chat:  # refuses to open the CLI when the guardrail self-test fails (Loop 4 step 8)
	bash scripts/selftest.sh
	$(COMPOSE) exec -u hermes -w /workspace -it orchestrator hermes --cli

test:
	cd services/kitchen_ledger && $(UV) run pytest tests/unit -q
	cd services/cockpit && $(UV) run pytest tests -q
	cd evals && $(UV) run pytest -q

# Reads the live app database seeded by `make up`.
test-integration:
	$(COMPOSE) up -d --wait postgres
	cd services/kitchen_ledger && $(UV) run pytest tests/integration -q

test-contracts:
	$(COMPOSE) run --rm --no-deps orchestrator $(AGENT_PYTHON) -m pytest /opt/kitchen/contracts/tests -q -p no:cacheprovider

test-plugins:
	$(COMPOSE) run --rm --no-deps orchestrator $(AGENT_PYTHON) -m pytest /opt/kitchen/plugins/tests -q -p no:cacheprovider

smoke-a2a:
	bash scripts/smoke_a2a.sh

smoke-research:  # live: real Tavily and model calls through the researcher contract
	bash scripts/smoke_research.sh

latency-report:  # where a turn's time goes, from the events and the audit log (PLAN.md C76). SINCE: ISO timestamp
	cd evals && $(UV) run python latency_report.py $(if $(SINCE),--since "$(SINCE)")

review-conversations:  # PL7: score her real CLI/Telegram conversations since SINCE=YYYY-MM-DD (default 7 days) into evals/reviews and Langfuse
	cd evals && $(UV) run python review_conversations.py $(if $(SINCE),--since $(SINCE),)

evals:  # every eval layer on the live stack; erases business state, so it needs KITCHEN_ALLOW_EVAL_RESET=1 (Loop 6). ARGS: --resume, --scenarios, --redteam, -k
	cd evals && $(UV) run python runner.py $(ARGS)

eval-guardrails:  # input guard over evals/guardrail_dataset.jsonl with the real classifier inside orchestrator (Loop 6)
	cd evals && $(UV) run python guardrail_eval.py

eval-reset:  # wipes the running stack's business state before a trial; refuses without KITCHEN_ALLOW_EVAL_RESET=1 (Loop 6)
	bash scripts/eval_reset.sh

eval-requirements:  # requirement extraction on fixture pages through researcher-eval (evals/NOTES.md)
	$(COMPOSE) --profile eval up -d --build --wait researcher-eval
	cd evals && uv run python requirements_eval.py

import-pantry:  # copy a spreadsheet where Dona Sálvia can import it: make import-pantry FILE=path/to/file.xlsx
	@test -n "$(FILE)" || { echo "usage: make import-pantry FILE=path/to/file.xlsx"; exit 1; }
	$(COMPOSE) cp "$(FILE)" orchestrator:/opt/data/cache/documents/$(notdir $(FILE))
	$(COMPOSE) exec -T orchestrator chown hermes:hermes /opt/data/cache/documents/$(notdir $(FILE))
	@echo "Diga à Dona Sálvia: atualizei minha planilha da despensa em /opt/data/cache/documents/$(notdir $(FILE))"

selftest:  # guardrail canary against orchestrator's API server (Loop 4)
	bash scripts/selftest.sh

# Hermes silently falls back to its default skin on invalid YAML, so the name must come back from the engine (Loop 7).
test-skin:
	$(COMPOSE) exec -T orchestrator python -c "from hermes_cli.skin_engine import load_skin; s=load_skin('dona-salvia'); assert 'Dona Sálvia' in str(s), 'dona-salvia skin not loaded'; from rich.text import Text; rows=[Text.from_markup(r).plain for r in s.banner_hero.splitlines()]; assert rows and len({len(r) for r in rows})==1 and all(r==r.rstrip() for r in rows), 'banner_hero rows need one width and no trailing spaces: Rich strips them and centers each row on its own'; assert len(rows[0])<=52, 'banner_hero is wider than 52 cells'"

db-shell:
	$(COMPOSE) exec postgres psql -U kitchen -d kitchen

# Shell inside the pinned Hermes image, to read the installed Hermes source during spikes.
hermes-shell:
	$(COMPOSE) run --rm --no-deps --entrypoint sh orchestrator
