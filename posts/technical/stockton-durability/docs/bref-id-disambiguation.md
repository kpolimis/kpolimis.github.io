# BRef Player ID Disambiguation — Finding & Resolution

**Discovered:** 2026-10-15  
**Issues:** blog-source #2 (wrong IDs), #3 (HOF asterisk)  
**Status:** Fixed; Wave 3 fetch running

---

## What happened

When the population cohort was built by scraping Basketball-Reference's player index pages, two bugs in `build_population_cohort()` caused players to be silently dropped or assigned the wrong ID.

### Bug 1 — Name-collision clobbering (16 wrong IDs)

The scraper built a page-level `name_to_pid` dict keyed on anchor text. When a letter page lists two players with the same display name (e.g. two "Dee Brown"s), the last anchor in the HTML overwrites the first. Every row with that name then gets the wrong player's ID. A downstream `drop_duplicates("player_id")` silently discarded the displaced twin.

**Example:** `brownde03` in the cohort pointed to Daniel "Dee" Brown (born 1984, 68 career games, Jazz) — not the Celtics Dee Brown (born 1968, 1991 dunk contest, ~12-season career). The wrong player's gamelog page returned zero rows, making Dee Brown appear completely absent from the data.

**16 affected players and their correct IDs:**

| Player | Wrong ID | Correct ID |
|:-------|:---------|:-----------|
| Dee Brown | brownde03 | brownde01 |
| Mark Davis | davisma02 | davisma01 |
| Cedric Henderson | hendece02 | hendece01 |
| Gerald Henderson | hendege02 | hendege01 |
| Mike James | jamesmi02 | jamesmi01 |
| Ken Johnson | johnske03 | johnske01 |
| Charles Jones | jonesch03 | jonesch01 |
| Mark Jones | jonesma03 | jonesma02 |
| Walker Russell | russewa02 | russewa01 |
| Charles Smith | smithch04 | smithch01 |
| Chris Smith | smithch05 | smithch03 |
| Michael Smith | smithmi02 | smithmi01 |
| Jeff Taylor | tayloje03 | tayloje01 |
| Brandon Williams | willibr03 | willibr01 |
| Marcus Williams | willima04 | willima03 |
| Reggie Williams | willire02 | willire01 |

Two of the wrong IDs happened to point to a *different real player* who had gamelog data — their rows were in the parquet under the wrong ID (95 rows total: 82 for the wrong Michael Smith, 13 for the wrong Marcus Williams). These were purged before the corrected fetch.

### Bug 2 — Hall of Fame asterisk (59 HOFers missing)

BRef marks Hall of Famers with a trailing asterisk in anchor text (e.g. `"Michael Jordan*"`). The scraper stripped the asterisk from the display name but the dict lookup key still contained it, so `name_to_pid.get("Michael Jordan")` returned `None`. Every in-scope HOFer was silently skipped.

**Impact:** ~59 Hall of Famers absent from the original 1,995-player cohort — including Jordan, Bird, Barkley, Olajuwon, Payton, Kidd, Nash, Duncan, and Garnett. For a durability study, this is meaningful: Hall of Famers are long-career by construction and belong at the high end of the durability distribution. Their absence would have understated the upper tail.

---

## Detection

Both bugs were caught during the Wave 1 fetch audit (2026-10-15). The 9 initially-identified "completely missing" multi-season players (Dee Brown, Gerald Henderson, etc.) were found to have 0 rows despite multi-year careers. Checking their BRef pages directly revealed the wrong birth year, confirming an ID mismatch.

A deeper analysis of the cached index HTML (`data/html_cache/index/_index_*.html`) identified all 16 collisions by matching `(name, debut_year, final_year)` against each letter page's actual row anchors — an offline, deterministic lookup requiring no new scraping.

---

## Fix

Replaced the page-level `name_to_pid` dict with **row-aligned PID extraction**: for each `<tr>` in the index table, the player ID is taken directly from that row's own `<th data-stat="player"><a href="...">` tag. This eliminates both the name-collision clobbering and the HOF asterisk miss (the `*` is stripped from anchor text before recording the name). The `drop_duplicates("player_id")` call was replaced with an assertion — a duplicate now raises an error rather than silently discarding a player.

---

## Cohort impact

| | Count |
|:--|:------|
| Original cohort | 1,995 |
| After rebuild | 2,067 |
| Net addition | +72 |
| Contaminated rows purged | 95 |

---

## For the population post

This finding is worth a brief methods note — it demonstrates the kind of data quality issue that arises when scraping a site with same-name disambiguation, and shows the audit process that caught it. Frame it as standard data validation, not as an error that undermined the analysis: the fix was applied before any population-level results were computed.

Suggested framing: *"During data validation, we identified 16 player IDs pointing to the wrong individual due to same-name disambiguation on Basketball-Reference, and a separate bug that excluded Hall of Famers marked with an asterisk in the index. Both were corrected before analysis; the final cohort covers 2,067 players."*
