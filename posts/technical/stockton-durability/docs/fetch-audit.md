# Fetch Audit — Final (Wave 3)

**Date:** 2026-10-16  
**Parquet:** `data/game_logs.parquet` (656,839 rows)  
**Cohort:** `data/population_cohort.csv` (2,067 players)

## Results

```
======================================================================
BASKETBALL-REFERENCE FETCH AUDIT
======================================================================
Game log rows:     656,839
Cohort players:    2,067
Fetched players:   2,067

--- Players completely missing: 0 ---

--- Players with missing seasons: 1,551 ---
(note: a missing mid-career season can be legitimate, e.g. overseas)

--- (player, season) pairs with <20 games: 1,554 ---
(flagged for review, not treated as fetch errors)

--- NULL rates (key columns) ---
  Date             0.00%
  MP               0.00%
  mp_float         0.00%
  PTS              0.00%
  player_id        0.00%
  season           0.00%
  player_name      0.00%

VERDICT: FETCH COMPLETE — 0 missing players; 1,551 season gaps (likely legitimate)
======================================================================
```

## Gap breakdown (`fetch_gaps.csv`: 3,960 rows)

| gap_type | count |
|---|---|
| missing_season | 2,406 |
| low_game_count | 1,554 |
| missing_player | 0 |

## Interpretation

**Missing seasons** (1,551 players, 2,406 season pairs) are expected at this scale. The debut/final year range from BRef's player index is a bounding box — it does not guarantee a game log exists for every year in between. Common legitimate causes:

- Mid-career overseas stints (Anthony Parker in Euroleague, Sergio Rodríguez, Shane Heal)
- Lockout-shortened seasons (1999, 2012) — players who didn't play at all that year have no game log page
- Career injuries or suspensions (Ron Harper missed parts of his career, 9 gaps flagged)
- 1-3 game NBA cups of coffee: some cohort members had a debut season then disappeared for years before resurfacing

None of the top "missing seasons" players (Ron Harper, Gary Plummer, Will Solomon, etc.) are in the primary PG or PF analysis cohorts. The population analysis uses game-level data for players who cleared the ≥600-game threshold, so sparse seasons are naturally excluded.

**Low game counts** (1,554 pairs) include lockout seasons, injury campaigns, and end-of-career cameos. These are legitimate observations to keep — a player who appeared in 5 games still counts as "having played that season."

## Before / after comparison

| Metric | Wave 1 (2026-10-15) | Wave 3 Final (2026-10-16) |
|:-------|:--------------------|:--------------------------|
| Rows | 589,793 | 656,839 |
| Cohort size | 1,995 | 2,067 |
| Fetched players | 1,552 | **2,067** |
| Missing players | 450 | **0** |
| Missing season pairs | 2,375 | 2,406 |
| NULL rate | 0.00% | 0.00% |
| Verdict | NEEDS SECOND WAVE | **FETCH COMPLETE** |

The increase in missing season pairs (2,375 → 2,406) reflects the larger cohort (+72 players), not a regression.

## Known issues resolved before Wave 3

- **Off-by-one on debut season** (`fetch_bref_data.py`): `debut_year + 1` incorrectly skipped every player's rookie season; removed `+ 1`
- **16 wrong player IDs** from name-collision clobbering; corrected via row-aligned HTML extraction (see `docs/bref-id-disambiguation.md`)
- **~59 HOFers absent** due to BRef `*` asterisk on Hall of Fame anchors; fixed by stripping `*` before recording player name
- **95 contaminated rows purged** (82 from wrong Michael Smith, 13 from wrong Marcus Williams)
- **VPN/DNS blocks on Apollo**: Wave 2 was completely blocked by BRef 403s on ProtonVPN IPs; Wave 3 ran locally on residential IP without issue
