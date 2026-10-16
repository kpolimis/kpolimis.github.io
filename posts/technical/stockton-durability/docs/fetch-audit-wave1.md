# Fetch Audit — Wave 1

**Date:** 2026-10-15  
**Parquet:** `data/game_logs.parquet` (589,793 rows, 15M)  
**Cohort:** `data/population_cohort.csv` (1,995 players)

## Results

```
======================================================================
BASKETBALL-REFERENCE FETCH AUDIT
======================================================================
Game log rows:     589,793
Cohort players:    1,995
Fetched players:   1,552

Players completely missing:          450
Players with ≥1 missing season:    1,534  (2,375 missing season pairs)
(player, season) pairs < 20 games: 1,228  (flagged, not errors)
NULL rate (all key columns):        0.00%

VERDICT: NEEDS SECOND WAVE
======================================================================
```

## Gap breakdown (fetch_gaps.csv: 4,053 rows)

| gap_type | count |
|---|---|
| missing_season | 2,375 |
| low_game_count | 1,228 |
| missing_player | 450 |

## Known issues fixed before Wave 2

- **Off-by-one on debut season** (`fetch_bref_data.py` line 391): `first = int(row["debut_year"]) + 1` incorrectly skipped every player's rookie season. BRef season IDs already use season-ending year, so `+ 1` is wrong. Fixed to `first = int(row["debut_year"])`.
- **DNS/403 casualties**: ~450 players had all requests fail during the run due to VPN instability and rate limiting. Wave 2 targets these via `fetch_gaps.csv`.
