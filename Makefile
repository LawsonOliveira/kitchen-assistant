COMPOSE := docker compose
UV := uv
AGENT_PYTHON := /opt/hermes/.venv/bin/python

.PHONY: up down logs chat test test-integration test-contracts test-plugins smoke-a2a smoke-research eval-requirements import-pantry selftest test-skin db-shell hermes-shell

up:
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs --no-log-prefix

# Classic prompt_toolkit CLI (--cli), as the hermes user, from the workspace that holds .hermes.md.
chat:  # refuses to open the CLI when the guardrail self-test fails (Loop 4 step 8)
	bash scripts/selftest.sh
	$(COMPOSE) exec -u hermes -w /workspace -it fifi hermes --cli

test:
	cd services/costs_mcp && $(UV) run pytest tests/unit -q
	cd services/cockpit && $(UV) run pytest tests -q

# Reads the live app database seeded by `make up`.
test-integration:
	$(COMPOSE) up -d --wait postgres
	cd services/costs_mcp && $(UV) run pytest tests/integration -q

test-contracts:
	$(COMPOSE) run --rm --no-deps fifi $(AGENT_PYTHON) -m pytest /opt/sabor/contracts/tests -q -p no:cacheprovider

test-plugins:
	$(COMPOSE) run --rm --no-deps fifi $(AGENT_PYTHON) -m pytest /opt/sabor/plugins/tests -q -p no:cacheprovider

smoke-a2a:
	bash scripts/smoke_a2a.sh

smoke-research:  # live: real Tavily and model calls through the researcher contract
	bash scripts/smoke_research.sh

eval-requirements:  # requirement extraction on fixture pages through researcher-eval (evals/NOTES.md)
	$(COMPOSE) --profile eval up -d --build --wait researcher-eval
	cd evals && uv run python requirements_eval.py

import-pantry:  # copy a spreadsheet where Dona Fifi can import it: make import-pantry FILE=path/to/file.xlsx
	@test -n "$(FILE)" || { echo "usage: make import-pantry FILE=path/to/file.xlsx"; exit 1; }
	$(COMPOSE) cp "$(FILE)" fifi:/opt/data/cache/documents/$(notdir $(FILE))
	$(COMPOSE) exec -T fifi chown hermes:hermes /opt/data/cache/documents/$(notdir $(FILE))
	@echo "Diga à Dona Fifi: atualizei minha planilha da despensa em /opt/data/cache/documents/$(notdir $(FILE))"

selftest:  # guardrail canary against fifi's API server (Loop 4)
	bash scripts/selftest.sh

# Hermes silently falls back to its default skin on invalid YAML, so the name must come back from the engine (Loop 7).
test-skin:
	$(COMPOSE) exec -T fifi python -c "from hermes_cli.skin_engine import load_skin; s=load_skin('dona-fifi'); assert 'Dona Fifi' in str(s), 'dona-fifi skin not loaded'"

db-shell:
	$(COMPOSE) exec postgres psql -U sabor -d sabor

# Shell inside the pinned Hermes image, to read the installed Hermes source during spikes.
hermes-shell:
	$(COMPOSE) run --rm --no-deps --entrypoint sh fifi
