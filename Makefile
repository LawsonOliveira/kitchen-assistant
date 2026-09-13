COMPOSE := docker compose
UV := uv
AGENT_PYTHON := /opt/hermes/.venv/bin/python

.PHONY: up down logs chat test test-integration test-contracts test-plugins smoke-a2a smoke-research db-shell hermes-shell

up:
	$(COMPOSE) up -d --build --wait

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs --no-log-prefix

# Classic prompt_toolkit CLI (--cli), as the hermes user, from the workspace that holds .hermes.md.
chat:
	$(COMPOSE) exec -u hermes -w /workspace -it fifi hermes --cli

test:
	cd services/costs_mcp && $(UV) run pytest tests/unit -q

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

db-shell:
	$(COMPOSE) exec postgres psql -U sabor -d sabor

# Shell inside the pinned Hermes image, to read the installed Hermes source during spikes.
hermes-shell:
	$(COMPOSE) run --rm --no-deps --entrypoint sh fifi
