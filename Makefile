.DEFAULT_GOAL := help

.PHONY: help preview render render-epl render-wc-leagues render-wc-epl \
        freeze-audit freeze-post \
        data data-refresh clean clean-freeze all bootstrap lint lint-fix check

# C4: all re-executes WC posts then renders the full site (freeze cache handles the rest)
all: data render-wc-leagues render-wc-epl render  ## Fetch data, re-execute WC posts, render full site

# C1: install footy from pinned git SHA; local editable still works as dev override
bootstrap:  ## Install all blog dependencies (footy requires SSH access to kpolimis/football)
	pip install git+ssh://git@github.com/kpolimis/football.git@80c1d74#subdirectory=footy
	# Local editable override (takes precedence; keep in sync with the SHA above):
	#   pip install -e ~/repos/football/footy
	pip install -r requirements.txt
	@echo "Bootstrap complete. Confirm versions: pip show footy soccerdata"

# C2: non-mutating lint — exits non-zero on errors so CI can gate on it
lint:  ## Check code style without modifying files (exits 1 on lint or format errors)
	conda run -n blog ruff check .
	conda run -n blog ruff format --check .

lint-fix:  ## Auto-fix lint and format issues in place
	conda run -n blog ruff check . --fix
	conda run -n blog ruff format .

# C2: full quality gate (lint + tests)
check: lint  ## Run full quality gate: lint, format check, then pytest
	conda run -n blog pytest

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-14s %s\n", $$1, $$2}'

preview:  ## Start local Quarto dev server (live reload)
	conda run -n blog quarto preview

render:  ## Render entire site (no execution; uses freeze cache)
	conda run -n blog quarto render

render-epl:  ## Re-execute and render EPL standings post
	conda run -n blog quarto render posts/blog/epl-standings/ --execute

# Freeze a post that needs local data unavailable in CI.
# Generic: make freeze-post POST=posts/technical/stockton-durability/audit.qmd
# The post's execute block must have freeze: true before running this.
freeze-audit:  ## Re-execute audit.qmd and write freeze cache (needs local parquets)
	conda run -n blog quarto render posts/technical/stockton-durability/audit.qmd --execute
	@echo "Done. Stage with: git add _freeze/posts/technical/stockton-durability/audit/"

freeze-post:  ## Re-execute any post and write its freeze cache: make freeze-post POST=<path>
	@test -n "$(POST)" || (echo "Usage: make freeze-post POST=<path/to/post.qmd>" && exit 1)
	conda run -n blog quarto render $(POST) --execute
	@echo "Done. Stage with: git add _freeze/"

# C4: render targets depend on data files so a data refresh forces re-execution
render-wc-leagues: data/wc_players.csv  ## Re-execute WC leagues post (needs data/)
	conda run -n blog quarto render posts/blog/world-cup-2026-leagues/ --execute

render-wc-epl: data/wc_rounds.csv  ## Re-execute WC EPL post (needs data/)
	conda run -n blog quarto render posts/blog/world-cup-2026-epl/ --execute

data:  ## Fetch 2026 World Cup data (uses soccerdata cache; no browser needed)
	conda run -n blog python posts/blog/world-cup-2026-leagues/fetch_wc_data.py

data-refresh:  ## Re-fetch 2026 World Cup data from FBref (opens Chrome)
	conda run -n blog python posts/blog/world-cup-2026-leagues/fetch_wc_data.py --refresh

# C3/D1: clean never touches _freeze/ — the committed freeze cache is what lets CI publish
clean:  ## Remove Quarto build outputs (keeps raw data, source files, and freeze cache)
	rm -rf _site/ .quarto/

# C3/D1: explicit escape hatch — only use if you will re-execute locally before pushing
clean-freeze:  ## Remove freeze cache — DANGEROUS: breaks CI until freeze outputs are recommitted
	@echo "WARNING: Deleting _freeze/ means CI cannot render posts that require local data or footy."
	@echo "Only do this if you plan to run render targets locally before pushing."
	@echo "Run 'make clean-freeze CONFIRM=yes' to proceed."
	@test "$(CONFIRM)" = "yes" || (echo "Aborted. Pass CONFIRM=yes to delete _freeze/." && exit 1)
	rm -rf _freeze/
