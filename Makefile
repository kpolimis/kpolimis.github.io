.DEFAULT_GOAL := help

.PHONY: help preview render data clean all bootstrap lint

all: data render-wc-leagues render-wc-epl  ## Fetch data then re-execute both WC posts end-to-end

bootstrap:  ## Install local footy package (editable) and pin soccerdata
	pip install -e ~/repos/football/footy
	pip install soccerdata
	@echo "Bootstrap complete. Run 'pip show soccerdata' to confirm version, then pin in requirements.txt."

lint:  ## Run Ruff linter across the repo
	conda run -n blog ruff check . --fix

help:  ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

preview:  ## Start local Quarto dev server (live reload)
	conda run -n blog quarto preview

render:  ## Render entire site (no execution; uses freeze cache)
	conda run -n blog quarto render

render-epl:  ## Re-execute and render EPL standings post
	conda run -n blog quarto render posts/blog/epl-standings/ --execute

render-wc-leagues:  ## Re-execute and render world-cup-2026-leagues post
	conda run -n blog quarto render posts/blog/world-cup-2026-leagues/ --execute

render-wc-epl:  ## Re-execute and render world-cup-2026-epl post
	conda run -n blog quarto render posts/blog/world-cup-2026-epl/ --execute

data:  ## Fetch 2026 World Cup data (uses soccerdata cache; no browser needed)
	conda run -n blog python posts/blog/world-cup-2026-leagues/fetch_wc_data.py

data-refresh:  ## Re-fetch 2026 World Cup data from FBref (opens Chrome)
	conda run -n blog python posts/blog/world-cup-2026-leagues/fetch_wc_data.py --refresh

clean:  ## Remove Quarto build artifacts (keeps raw data and source files)
	rm -rf _site/ .quarto/ _freeze/
