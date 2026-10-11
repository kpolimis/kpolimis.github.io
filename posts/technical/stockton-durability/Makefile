# Stockton Durability Analysis Pipeline
# Run all targets in dependency order from this directory.
# Assumes: conda run -n blog python ... or source activate blog

PYTHON = conda run -n blog python
DATA   = data

.PHONY: all test clean-cache cohort-pg cohort-pf summary \
        analyze-pg analyze-pf \
        quarter-splits-pg quarter-splits-pf \
        e2e5-pg e2e5-pf \
        population-build population-fetch analyze-population \
        render-stockton render-diaw render-population

# ── Top-level targets ────────────────────────────────────────────────────────

all: test

test:
	$(PYTHON) -m pytest tests/ -v --tb=short

# ── Data fetch ───────────────────────────────────────────────────────────────

# Fetch PG cohort (~2.5h wall time from scratch; incremental on re-run)
cohort-pg: $(DATA)/game_logs.parquet
$(DATA)/game_logs.parquet:
	$(PYTHON) fetch_bref_data.py --cohort pg

# Fetch PF cohort (~30 min wall time; appends to game_logs.parquet)
cohort-pf:
	$(PYTHON) fetch_bref_data.py --cohort pf

# Print/save cohort threshold summary (run after cohort-pg + cohort-pf)
summary:
	$(PYTHON) fetch_bref_data.py --summary

# ── Durability analysis ──────────────────────────────────────────────────────

# E1 + E3 for PG cohort; writes data/pg_comparators.csv + figures
analyze-pg: $(DATA)/pg_comparators.csv
$(DATA)/pg_comparators.csv: $(DATA)/game_logs.parquet
	$(PYTHON) analyze_durability.py --cohort pg

# E1 + E3 for PF cohort; writes data/pf_comparators.csv + figures
analyze-pf: $(DATA)/pf_comparators.csv
$(DATA)/pf_comparators.csv: $(DATA)/game_logs.parquet
	$(PYTHON) analyze_durability.py --cohort pf

# ── Quarter splits ───────────────────────────────────────────────────────────

# Fetch quarter splits for PG cohort comps (needs pg_comparators.csv first)
quarter-splits-pg: $(DATA)/quarter_splits_pg.parquet
$(DATA)/quarter_splits_pg.parquet: $(DATA)/pg_comparators.csv
	$(PYTHON) fetch_quarter_splits.py \
	    --comps-file $(DATA)/pg_comparators.csv \
	    --seasons 1996-2003

# Fetch quarter splits for PF cohort comps (needs pf_comparators.csv first)
quarter-splits-pf: $(DATA)/quarter_splits_pf.parquet
$(DATA)/quarter_splits_pf.parquet: $(DATA)/pf_comparators.csv
	$(PYTHON) fetch_quarter_splits.py \
	    --comps-file $(DATA)/pf_comparators.csv

# ── Within-game analysis ─────────────────────────────────────────────────────

# E2/E4/E5 for PG cohort
e2e5-pg: $(DATA)/quarter_splits_pg.parquet
	$(PYTHON) analyze_quarter_splits.py --cohort pg

# E2/E4/E5 for PF cohort
e2e5-pf: $(DATA)/quarter_splits_pf.parquet
	$(PYTHON) analyze_quarter_splits.py --cohort pf

# ── Population study ─────────────────────────────────────────────────────────

# Step 1: scrape BRef index pages A–Z to build population_cohort.csv (~30 min)
population-build: $(DATA)/population_cohort.csv
$(DATA)/population_cohort.csv:
	$(PYTHON) fetch_bref_data.py --build-population

# Step 2: fetch game logs for all population candidates (~hours wall time)
population-fetch: $(DATA)/population_cohort.csv
	$(PYTHON) fetch_bref_data.py --population-fetch

# Step 3: E1 + E3 for population cohort
analyze-population: $(DATA)/population_outliers.csv
$(DATA)/population_outliers.csv: $(DATA)/game_logs.parquet
	$(PYTHON) analyze_durability.py --cohort population

# ── Quick test (subset fetch, 5 players) ────────────────────────────────────
population-test:
	$(PYTHON) fetch_bref_data.py --population-fetch --limit 5

# ── Quarto rendering ─────────────────────────────────────────────────────────
render-stockton:
	cd ../../.. && quarto render posts/technical/stockton-durability/index.qmd

render-diaw:
	cd ../../.. && quarto render posts/technical/diaw-35bpm/index.qmd

render-population:
	cd ../../.. && quarto render posts/technical/nba-durability-population/index.qmd

# ── Cleanup ──────────────────────────────────────────────────────────────────
clean-cache:
	rm -rf $(DATA)/html_cache/quarter/*.html
	@echo "Quarter HTML cache cleared (re-run will re-fetch from BRef)"
