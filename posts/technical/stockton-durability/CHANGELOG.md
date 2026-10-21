# Changelog

All notable changes to the stockton-durability analysis pipeline.

## [Unreleased]

### Added
- `_rotate_vpn()` in `fetch_quarter_splits.py` — VPN rotation via Gluetun control API on HTTP 403 hard-blocks
- E8 fetch mode (`--top-n-by-games 50`) in `fetch_quarter_splits.py` for population-scale within-game analysis
- Population study analysis pass in `analyze_durability.py` (`--cohort population`)
- E7 career TS% analysis with TSA threshold sensitivity (`compute_e7_career_shooting`)
- `send_progress_email.py` — PDF progress reports via claude-notify
- `audit_fetch.py` — post-fetch data quality audit (missing players/seasons, low game counts, NULL rates)
- `README.md`, `CHANGELOG.md`, `.env.example`, folder-level `pyproject.toml` and `.gitignore`

### Fixed
- Incremental save trigger in `fetch_quarter_splits.py`: replaced modulo with delta counter to prevent skipped saves
- HTTP 429 handler reverted to wait-only (rotation caused infinite loop when BRef rate-limits entire VPN pool)
- BRef HOF asterisk stripping bug in `fetch_bref_data.py` — was silently excluding ~59 Hall of Famers
- Player name deduplication bug — second "Dee Brown" was overwriting first in name→ID dict

### Changed
- Population cohort threshold to ≥400 games (BRef's own qualifying minimum for career rate stats)
- Module-level `.mkdir()` side effects moved into `_ensure_dirs()` called from `main()` only

## [0.1.0] — 2026-10-14

### Added
- Initial PG + PF cohort fetch and analysis pipeline
- E1 (games missed per 82), E3 (B2B shot selection), E2/E4/E5 (within-game via quarter splits)
- Permutation inference framework (n=5,000 reassignments) throughout
- HTML caching layer for BRef requests
- Docker Compose setup for Apollo deployment (`bref-qs-fetch` + `gluetun-bref` containers)
- Test suite for fetch parsing, analysis functions, and pipeline integration
