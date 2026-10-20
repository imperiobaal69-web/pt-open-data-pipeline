# pt-open-data-pipeline: one entrypoint for every step.
#   make all                  # offline, on committed fixtures (default)
#   make all SOURCE=live      # full refresh from the INE API
SOURCE ?= fixtures
UV     ?= uv
PTDATA  = $(UV) run ptdata --source $(SOURCE)
DATA    = data/$(SOURCE)

.PHONY: all install extract load transform export report docs docs-serve test lint ci clean

all: install
	$(PTDATA) all

install:
	$(UV) sync --frozen

extract:
	$(PTDATA) extract

load:
	$(PTDATA) load

transform:
	$(PTDATA) transform

export:
	$(PTDATA) export

report:
	$(PTDATA) report

docs:
	$(PTDATA) docs

docs-serve:
	PTDATA_DUCKDB=$(abspath $(DATA))/warehouse.duckdb $(UV) run dbt docs serve \
		--project-dir transform --profiles-dir transform --target-path $(abspath $(DATA))/dbt_target

test:
	$(UV) run pytest -q

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .

# What CI runs: lint, unit + end-to-end tests, the full fixture pipeline, and a
# check that the generated fixture report and lineage diagram are up to date.
ci: install lint test
	$(MAKE) all SOURCE=fixtures
	git diff --exit-code -- reports/summary_fixtures.md docs/lineage.md

clean:
	rm -rf $(DATA)
