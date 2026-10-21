# Stockton Durability Analysis Pipeline
# Run all targets in dependency order from this directory.
# Assumes: conda run -n blog python ... or source activate blog

PYTHON = conda run -n blog python
DATA   = data

.DEFAULT_GOAL := help

.PHONY: all help install lint check test clean-cache \
        cohort-pg cohort-pf summary \
        analyze-pg analyze-pf \
        quarter-splits-pg quarter-splits-pf \
        e2e5-pg e2e5-pf \
        population-build population-fetch analyze-population \
        population-test \
        render-stockton render-diaw render-population

# ── Top-level targets ────────────────────────────────────────────────────────

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?##' $(MAKEFILE_LIST) | awk 'BEGIN {FS=":.*?## "}; {printf "  %-22s %s\n", $$1, $$2}'

all: check ## Run full check suite (lint + test)

install: ## Install Python dependencies
	pip install -r requirements.txt

lint: ## Run ruff check + format check
	ruff check .
	ruff format --check .

check: lint test ## Run lint + test

test: ## Run test suite
	$(PYTHON) -m pytest tests/ -v --tb=short

# ── Data fetch ───────────────────────────────────────────────────────────────

cohort-pg: $(DATA)/game_logs.parquet ## Fetch PG cohort game logs (~2.5h from scratch; incremental)
$(DATA)/game_logs.parquet:
	$(PYTHON) fetch_bref_data.py --cohort pg

cohort-pf: ## Fetch PF cohort game logs (~30 min; appends to game_logs.parquet)
	$(PYTHON) fetch_bref_data.py --cohort pf

summary: ## Print/save cohort threshold summary (run after cohort-pg + cohort-pf)
	$(PYTHON) fetch_bref_data.py --summary

# ── Durability analysis ──────────────────────────────────────────────────────

analyze-pg: $(DATA)/pg_comparators.csv ## E1 + E3 for PG cohort; writes pg_comparators.csv + figures
$(DATA)/pg_comparators.csv: $(DATA)/game_logs.parquet
	$(PYTHON) analyze_durability.py --cohort pg

analyze-pf: $(DATA)/pf_comparators.csv ## E1 + E3 for PF cohort; writes pf_comparators.csv + figures
$(DATA)/pf_comparators.csv: $(DATA)/game_logs.parquet
	$(PYTHON) analyze_durability.py --cohort pf

# ── Quarter splits ───────────────────────────────────────────────────────────

quarter-splits-pg: $(DATA)/quarter_splits_pg.parquet ## Fetch PG quarter splits (needs pg_comparators.csv)
$(DATA)/quarter_splits_pg.parquet: $(DATA)/pg_comparators.csv
	$(PYTHON) fetch_quarter_splits.py \
	    --comps-file $(DATA)/pg_comparators.csv \
	    --seasons 1996-2003

quarter-splits-pf: $(DATA)/quarter_splits_pf.parquet ## Fetch PF quarter splits (needs pf_comparators.csv)
$(DATA)/quarter_splits_pf.parquet: $(DATA)/pf_comparators.csv
	$(PYTHON) fetch_quarter_splits.py \
	    --comps-file $(DATA)/pf_comparators.csv

# ── Within-game analysis ─────────────────────────────────────────────────────

e2e5-pg: $(DATA)/quarter_splits_pg.parquet ## E2/E4/E5 within-game analysis for PG cohort
	$(PYTHON) analyze_quarter_splits.py --cohort pg

e2e5-pf: $(DATA)/quarter_splits_pf.parquet ## E2/E4/E5 within-game analysis for PF cohort
	$(PYTHON) analyze_quarter_splits.py --cohort pf

# ── Population study ─────────────────────────────────────────────────────────

population-build: $(DATA)/population_cohort.csv ## Scrape BRef A–Z index to build population_cohort.csv (~30 min)
$(DATA)/population_cohort.csv:
	$(PYTHON) fetch_bref_data.py --build-population

population-fetch: $(DATA)/population_cohort.csv ## Fetch game logs for all population candidates (~hours)
	$(PYTHON) fetch_bref_data.py --population-fetch

analyze-population: $(DATA)/population_outliers.csv ## E1/E3/E7 for population cohort
$(DATA)/population_outliers.csv: $(DATA)/game_logs.parquet
	$(PYTHON) analyze_durability.py --cohort population

population-test: ## Quick subset fetch for 5 players (smoke test)
	$(PYTHON) fetch_bref_data.py --population-fetch --limit 5

# ── Quarto rendering ─────────────────────────────────────────────────────────

render-stockton: ## Render Stockton post via Quarto
	cd ../../.. && quarto render posts/technical/stockton-durability/index.qmd

render-diaw: ## Render Diaw post via Quarto
	cd ../../.. && quarto render posts/technical/diaw-35bpm/index.qmd

render-population: ## Render population post via Quarto
	cd ../../.. && quarto render posts/technical/nba-durability-population/index.qmd

# ── Cleanup ──────────────────────────────────────────────────────────────────

clean-cache: ## Clear quarter HTML cache (re-run will re-fetch from BRef)
	rm -rf $(DATA)/html_cache/quarter/*.html
	@echo "Quarter HTML cache cleared"
