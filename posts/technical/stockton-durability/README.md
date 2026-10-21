# NBA Durability Series — Analysis Pipeline

Permutation-inference analysis of career durability signals for John Stockton, Boris Diaw,
and the full BRef-era player population. Supports three blog posts published at
[kpolimis.github.io](https://kpolimis.github.io).

## Prerequisites

- Python 3.10+
- Dependencies: `pip install -r requirements.txt`
- [Quarto](https://quarto.org) (for rendering blog posts only)
- Internet access to Basketball-Reference (scraping; ~18h wall time from scratch)

## Quickstart

```bash
make install       # install dependencies
make check         # lint + test (no data required)

make cohort-pg     # fetch PG game logs (~2.5h)
make cohort-pf     # fetch PF game logs (~30min, appends)
make analyze-pg    # E1 + E3 for PG cohort
make analyze-pf    # E1 + E3 for PF cohort
make e2e5-pg       # E2/E4/E5 within-game for PG
make e2e5-pf       # E2/E4/E5 within-game for PF

make population-build    # scrape BRef A–Z index (~30min)
make population-fetch    # fetch population game logs (~18h)
make analyze-population  # E1/E3/E7 at population scale

make help          # full target list
```

## Data Flow

```
fetch_bref_data.py          → data/game_logs.parquet
                            → data/population_cohort.csv
fetch_quarter_splits.py     → data/quarter_splits_{pg,pf,e8}.parquet
analyze_durability.py       → data/figures/{pg,pf,population}/
                            → data/{cohort}_comparators.csv
analyze_quarter_splits.py   → data/figures/{pg,pf}/e{2,4,5,6}_*.png
```

Output figures are referenced directly by the Quarto `.qmd` posts.

## Scripts

| Script | Purpose |
|:-------|:--------|
| `fetch_bref_data.py` | Scrape BRef game logs; build population cohort index |
| `fetch_quarter_splits.py` | Scrape PBP quarter-level splits for within-game analysis |
| `analyze_durability.py` | E1 (games missed), E3 (B2B shot selection), E7 (career TS%) |
| `analyze_quarter_splits.py` | E2/E4/E5 within-game resilience via mixed-effects permutation |
| `audit_fetch.py` | Interactive audit: missing players/seasons, NULL rates |
| `send_progress_email.py` | Render progress docs to PDF and email via claude-notify |
| `fetch_season_splits.py` | Season-level split fetcher (supplementary) |

## Environment Variables

See `.env.example` for all supported variables. Key ones:

| Variable | Default | Purpose |
|:---------|:--------|:--------|
| `GLUETUN_CTRL_URL` | `""` | Gluetun VPN control API URL; enables VPN rotation on HTTP 403 |
| `SESSION_COOLDOWN_PAGES` | `100` | Pages between session cooldown sleeps |
| `SESSION_COOLDOWN_SEC` | `300` | Cooldown duration in seconds |
| `MAX_403_BACKOFF_SEC` | `600` | Maximum backoff for HTTP 403 responses |

## Tests

```bash
make test
# or
pytest tests/ -v --tb=short
```

Tests are designed to run without network access or pre-fetched data. Data-dependent
tests are skipped automatically when `data/game_logs.parquet` is absent.

## Data Notes

- `data/` is gitignored except for pre-computed figures (needed for blog rendering)
- Large files (`game_logs.parquet`, `population_cohort.csv`, permutation parquets) are
  not tracked — regenerate from scratch via `make cohort-pg cohort-pf population-fetch`
- HTML cache (`data/html_cache/`) is gitignored; re-fetch warms cache automatically

## Blog Posts

| Post | File |
|:-----|:-----|
| John Stockton durability | `index.qmd` |
| Boris Diaw (35 BPM) | `../diaw-35bpm/index.qmd` |
| Population study | `../nba-durability-population/index.qmd` |

Render via `make render-stockton` / `render-diaw` / `render-population` (requires Quarto
and a complete `data/` directory).
