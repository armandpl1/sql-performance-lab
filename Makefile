# Local commands. `make ci` mirrors the CI lint and test jobs;
# `make integration` mirrors the CI integration job (needs Docker).

RUN := uv run

.PHONY: help install hooks lint test ci db-up db-down data data-small load \
        storage check integration lab clean

help:  ## List targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install:  ## Install dependencies from uv.lock
	uv sync --locked

hooks:  ## Install the git pre-commit hooks
	$(RUN) pre-commit install

lint:  ## Lint and check formatting (same hooks as CI)
	uv lock --check
	$(RUN) pre-commit run --all-files

test:  ## Unit tests: SQL parsing, generator, plan analyzer
	$(RUN) pytest

ci: lint test  ## What CI runs before the database job

db-up:  ## Start PostgreSQL (waits until healthy)
	docker compose up -d --wait

db-down:  ## Stop PostgreSQL (data volume kept; add -v to delete it)
	docker compose down

data:  ## Full dataset: 10M transactions, 20M events (~2 min)
	$(RUN) python scripts/generate_data.py

data-small:  ## Small dataset for quick checks and CI
	$(RUN) python scripts/generate_data.py --transactions 200000 --events 400000 \
		--accounts 20000 --chunk-size 50000

load:  ## Load data/ into PostgreSQL and build baseline indexes
	$(RUN) python scripts/load_data.py

storage:  ## Build the Step 4 storage layouts
	for f in sql/storage/*.sql; do $(RUN) python scripts/run_sql.py "$$f"; done

check:  ## Prove optimized queries return identical results
	$(RUN) python scripts/check_equivalence.py

integration: db-up data-small load storage check  ## The CI integration job, locally

lab:  ## Run every step at full scale (timings, plans, reports)
	scripts/run_lab.sh

clean:  ## Remove CI outputs
	rm -rf reports
