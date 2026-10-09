---
title: "Artifact & Plot Specs — Stockton Durability Series"
subtitle: "Interactive and static visualization decisions for Posts 1–4"
date: "2026-10-09"
---

Visual standards source: `~/repos/standards-playbook/VISUAL_STANDARDS.md`
Core rules applied throughout: one chart one question [§1.5], position > length > area > color [§1.4 Cleveland], data-ink ratio [§1.1 Tufte], direct labels over legends for ≤5 series [§11.2], Okabe-Ito qualitative palette [§8.2].

---

## Interactivity triage

Interactive is justified when the user needs to explore across players or conditions.
Static is correct when the finding is singular and a caption + annotation can carry it.

| Artifact | Type | Post(s) |
|:---------|:-----|:--------|
| Durability Explorer (E1) | Interactive OJS | 1, 2 |
| Quarter Profile (E6) | Interactive OJS | 1, 2 |
| Population Placement | Interactive OJS | 3, 4 |
| B2B Shot Selection (E3) | Static | 1, 2 |
| Permutation Null (E1, E3) | Static | 1, 2 |
| Within-Game Panel (E2/E4/E5) | Static small multiples | 1, 2 |

---

## A1 — Durability Explorer (E1)

**Post:** 1 (Stockton), reused for Post 2 (Diaw) with PF data swapped in.

**One question:** Who was the most durable point guard of their era?

**Chart type:** Dot plot, horizontal, sorted ascending by games missed per 82.
Rationale: task is categorical comparison; position is the correct encoding (Cleveland §6); dot plot beats bar because zero baseline adds no meaning to a ratio that is never near zero across this cohort.

**Encodings:**
- x: games missed per 82 (lockout-corrected denominator)
- y: player name, sorted by x ascending (Stockton at top)
- Color: Okabe-Ito orange (`#E69F00`) for treated player; neutral `#AAAAAA` for comparators
- Size/shape: uniform circle; no bubble sizing

**Interactivity:**
- Hover tooltip: player name, games missed per 82, career span, mean MPG, total seasons
- One sort toggle: by games missed per 82 (default) vs. alphabetical
- No animation, no era filter, no threshold slider — those belong in prose

**Static annotation (always visible):**
- Direct label on treated player's dot showing exact value
- Faint vertical reference line at cohort median, labeled "PG median" (or "PF median" for Post 2)
- Caption: BRef source, lockout seasons corrected (1999/2012/2020/2021), MPG threshold, career window

**Title formula:** "[Player] missed fewer games per 82 than any comparable [position] in BRef history"

**Python output needed:** `data/pg_e1_results.csv` with columns `player_name`, `games_missed_per_82`, `career_span`, `total_seasons`, `mean_mpg`, `is_treated`. Check whether `analyze_durability.py` emits this or only `pg_comparators.csv`; add `--emit-e1-summary` flag if not.

**Implementation:** OJS cell in `index.qmd` using `Plot.dot()` + `Plot.ruleX()` for median line. ~30 lines OJS. CSV fetched client-side at render time.

---

## A2 — Quarter Profile (E6)

**Post:** 1 (Stockton), reused for Post 2 (Diaw).

**One question:** Does the treated player's scoring/efficiency profile flatten from Q1 to Q4 less than comparators?

**Chart type:** Line chart, Q1→Q2→Q3→Q4 on x-axis, metric on y-axis, one line per player.
Rationale: task is trend over an ordered sequence (quarters); line chart is correct [§5, VISUAL_STANDARDS chart-type table]. Position encodes the pattern shape — that is what the reader needs to judge.

**Encodings:**
- x: quarter (Q1, Q2, Q3, Q4) — ordinal, evenly spaced
- y: selected metric (FT%, TS%, AST/TOV — dropdown controlled)
- Color: treated player in Okabe-Ito orange; 3–4 closest comps in sequential grays; remaining comps de-emphasized or hidden by default
- Line weight: treated player 2.5px; comps 1px

**Interactivity:**
- Metric dropdown: FT%, TS%, AST/TOV (three OJS select options mapping to E2/E5/E4 columns)
- Player toggle: show/hide individual comparators. Default shows treated + 3 closest comps only.
- Hover on any point: player name, quarter, metric value, n_games contributing to that cell

**Static annotation (always visible):**
- Direct label at Q4 end of treated player's line
- If treated player's Q4 value is notably above cohort mean, annotate with a callout; if null, no callout (null is a valid result — state it plainly in prose)

**What this is NOT:** not a faceted per-player panel (that would answer "what is each player's profile" — a different question); not a bar chart per quarter.

**Title formula:** "[Player]'s [metric] held steady through Q4 — [comps] declined by X points"
or if null: "[Player] showed no detectable Q4 decline in [metric], consistent with cohort pattern"

**Python output needed:** `data/pg_quarter_splits.csv` (or parquet) with columns `player_id`, `player_name`, `quarter`, `ft_pct`, `ts_pct`, `ast_tov`, `is_treated`, `n_games`. Emitted by `analyze_quarter_splits.py`.

**Implementation:** OJS cell with `Plot.line()` + `Plot.dot()`. Metric dropdown via `Inputs.select()`. ~50 lines OJS.

---

## A3 — B2B Shot Selection (E3)

**Post:** 1 (Stockton), reused for Post 2 (Diaw). Static — no interactivity needed.

**One question:** Does the treated player's shot selection (3PA/FGA, FTA/FGA) shift less on back-to-back nights than comparators?

**Chart type:** Connected dot plot. Two dots per player per metric: one for rested games, one for B2B games, connected by a thin line. Players sorted by magnitude of B2B shift, descending. Treated player highlighted.
Rationale: task is "show change between two conditions per unit" — connected dot plot is the canonical choice [§5, Cleveland §6]. The direction and magnitude of the line segment is the finding.

**Encodings:**
- x: metric value (3PA/FGA or FTA/FGA; one panel per metric via small multiples / patchwork)
- y: player name, sorted by absolute B2B shift
- Color of dot: rested = filled circle, B2B = hollow circle (shape distinguishes condition without adding a second color)
- Line color: Okabe-Ito orange for treated, `#AAAAAA` for comparators

**No interactivity.** The finding is directional (treated player's line is shorter = less shift). A static small-multiple communicates this cleanly. Adding hover would not add interpretive value.

**Static annotation:**
- Treated player labeled directly
- Caption: what B2B is defined as (game on consecutive calendar days), n_games per condition

**Output needed:** `data/pg_e3_results.csv` with `player_name`, `condition` (rested/b2b), `metric` (3pa_fga/fta_fga), `value`, `is_treated`. Emitted by `analyze_durability.py`.

---

## A4 — Permutation Null Distribution

**Post:** 1 and 2, one panel per primary estimand (E1, E3). Static.

**One question:** Is the treated player's observed gap from the cohort extreme relative to what random label assignment would produce?

**Chart type:** Histogram of 5,000 permuted gaps, with a vertical line marking the observed gap.
Rationale: the distribution IS the finding; a histogram is the correct encoding for a sampling distribution [§5, distribution task]. Bar chart of means would hide the shape.

**Encodings:**
- x: permuted gap value (treated − median comparator, or similar)
- y: count (histogram bins)
- Fill: neutral gray for null distribution bars
- Vertical line: Okabe-Ito orange at observed gap value, labeled with the one-sided p-value ("p = 0.003")

**No interactivity.** One-shot inference result. The reader does not need to explore; they need to see where the observed value falls.

**Annotation:**
- Vertical reference line with value + p-value label
- Subtitle: what is being permuted (treatment label across players, 5,000 iterations)
- Shaded region: right tail beyond observed value (light orange fill) to make the p-value area visible

**Output needed:** The 5,000 permuted values as a column in `data/pg_permutation_null.csv`. `analyze_durability.py` should emit this alongside the point estimates.

---

## A5 — Within-Game Resilience Panel (E2/E4/E5)

**Post:** 1 and 2. Static small multiples.

**One question per panel:**
- E2: Does FT% degrade in Q4 vs Q1–Q3?
- E4: Does AST/TOV ratio decline in Q4?
- E5: Does TS% drop in Q4?

**Chart type:** Small-multiples dot plot (one panel per estimand), x = quarter effect size (treated − cohort mean), y = estimand label, with 95% permutation interval shown as a horizontal line segment.
Rationale: the finding is a coefficient (quarter × is_treated interaction term from MixedLM), not a distribution. A coefficient plot (also called a forest plot) is the correct encoding for estimated effects with uncertainty bands.

**Encodings:**
- x: effect size (Q4 interaction coefficient), centered at zero
- y: estimand (E2, E4, E5) — three rows
- Point: estimate; horizontal error bar: 95% permutation interval
- Color: Okabe-Ito orange if interval excludes zero, `#AAAAAA` if it includes zero
- Vertical reference line at x = 0 (no effect)

**No interactivity.** Coefficient plots are already the minimal encoding for this question.

**Annotation:**
- Axis label: "Q4 interaction effect (treated − cohort)"
- Reference line labeled "No difference"
- If interval excludes zero: direct label "p < 0.05 (permutation)"

**Output needed:** `data/pg_quarter_effects.csv` with `estimand`, `effect`, `ci_lo`, `ci_hi`. Emitted by `analyze_quarter_splits.py`.

---

## A6 — Population Placement (Post 3)

**Post:** 3 (all qualifying guards + forwards), referenced back from Posts 1 and 2.

**One question:** Where do Stockton and Diaw fall in the full distribution of BRef-era guards and forwards on durability?

**Chart type:** Strip plot (beeswarm) with density overlay. All qualifying players as dots on a single axis (games missed per 82), jittered vertically to avoid overplotting. Stockton and Diaw highlighted.
Rationale: task is "show distribution across many units with individual identification" — beeswarm is the correct choice at N ≈ 100–300 [§6.9, VISUAL_STANDARDS]; violin alone hides the individual points; bar chart of means is wrong.

**Encodings:**
- x: games missed per 82
- y: jitter (beeswarm algorithm)
- Color: Okabe-Ito orange for Stockton, Okabe-Ito blue (`#0072B2`) for Diaw, `#CCCCCC` for all others
- Size: uniform; no bubble encoding

**Interactivity:**
- Hover tooltip: player name, value, position, career span
- Position filter: Guards / Forwards / Both (radio buttons). Default: Both, since the comparison across positions is the point of Post 3.
- Era filter: pre-2000 / 2000–2010 / post-2010 (optional; include only if the era stratification is substantively relevant to the cherry-picking defense argument)

**Static annotation:**
- Direct labels for Stockton and Diaw only
- Vertical lines at their values with labels, so they remain legible at any zoom

**Output needed:** `data/population_e1_results.csv` (built when Post 3 analysis runs); same schema as `pg_e1_results.csv` plus `position` column.

---

## Cross-post notes

**Consistent encoding across posts:**
- Treated player is always Okabe-Ito orange (`#E69F00`) regardless of position or post
- Comparator points/lines are always `#AAAAAA` unless directly discussed
- The same axis range is used for E1 across Posts 1, 2, and 3 to enable visual comparison across posts (shared scales for cross-unit comparison, [§10.2 Tufte/Wilke])

**What is NOT built:**
- No combined Stockton+Diaw interactive in Posts 1 or 2 — each post is self-contained
- No 3D charts [§3.2, never use 3D for data encodable in 2D]
- No animation
- No dual-axis charts [§10.4, strongly discouraged]
- No radar/spider charts [§5, "area distorts"]

**Implementation order:**
A1 and A3 can be built as soon as `analyze_durability.py --cohort pg` runs.
A2 and A5 require `analyze_quarter_splits.py --cohort pg`.
A4 requires the permutation output from `analyze_durability.py` (check if it emits it currently).
A6 is a separate session (Post 3).

---

## Data Artifacts (DA)

**Status: optional.** Visualizations (A1–A6) ship regardless. Data artifacts are published only if there is time and the derived datasets are clean enough to stand alone. Do not block post publication on DA completion.

Downloadable datasets published alongside the posts. These are derived work — not raw BRef logs (don't distribute those). Another analyst can use these without re-scraping.

Each artifact ships as parquet + CSV with a `DATA_README.md` in `data/` documenting columns, provenance, and methodology. Linked from the post as "Download the data."

**DA1 — Lockout-corrected durability panel**
BRef does not publish per-season games-missed-per-82 with lockout denominators applied. This is the E1 output: one row per player-season, with `games_missed`, `games_scheduled` (lockout-corrected), `games_missed_per_82`, `season`, `player_id`, `cohort`. The lockout correction (1999→50, 2012→66, 2020→65, 2021→72) and the methodology note are what make this a citable artifact.
Available after: `analyze_durability.py --cohort pg` + `--cohort pf`.

**DA2 — Back-to-back game flag panel**
The B2B classification for every game in the cohort game log. BRef does not expose rest days directly — they must be derived from consecutive schedule dates. Columns: `player_id`, `game_date`, `is_b2b`, `rest_days`, `season`, `opponent`. Useful for any within-game fatigue or load-management study beyond this series.
Available after: `fetch_bref_data.py` (derived from `game_logs.parquet`; may need a small emit step in `analyze_durability.py`).

**DA3 — Quarter box score longitudinal panel**
BRef has per-season quarter splits but not as a clean player-season-quarter panel with B2B flags and rest days merged in. Columns: `player_id`, `season`, `quarter`, `ft_pct`, `ts_pct`, `ast_tov`, `fga`, `n_games`, `is_treated`. The merge of quarter splits with the rest-day panel is the derived value.
Available after: `analyze_quarter_splits.py --cohort pg`.

**DA4 — Cohort eligibility table**
The documented list of every player considered, whether they qualified, and why. Columns: `player_name`, `player_id`, `position`, `career_span`, `total_games`, `mean_mpg`, `qualified` (bool), `exclusion_reason`. Terry Porter (27.8 MPG, below threshold) is a canonical example. This is the methodological transparency artifact — it lets readers audit the cohort selection themselves.
Available after: `analyze_durability.py` (derived from the same threshold-filtering logic).

---

---

## DATA_README.md format

One file at `posts/technical/stockton-durability/data/DATA_README.md`. Covers all DA files in one place. Template:

```markdown
# Data — Stockton Durability Series

Derived datasets from "Can We See John Stockton's Heart Rate in the Box Score?"
Raw game logs scraped from Basketball Reference (bref.com); do not redistribute raw logs.
Derived outputs below are original analytical work and may be freely reused with attribution.

Last updated: YYYY-MM-DD | Scripts: fetch_bref_data.py, analyze_durability.py, analyze_quarter_splits.py

---

## pg_e1_results.csv / .parquet (DA1)
Lockout-corrected games-missed-per-82 for the 15-player PG cohort.

| Column | Type | Description |
|:-------|:-----|:------------|
| player_id | str | BRef player ID |
| player_name | str | Full name |
| season | int | Season start year (e.g. 1996 = 1996-97) |
| games_played | int | Games played that season |
| games_scheduled | int | Lockout-corrected season length (82, or 50/66/65/72 for shortened seasons) |
| games_missed | int | games_scheduled − games_played |
| games_missed_per_82 | float | games_missed / games_scheduled * 82 |
| mean_mpg | float | Mean minutes per game that season |
| cohort | str | "pg" |
| is_treated | bool | True for Stockton only |

Lockout corrections: 1999→50, 2012→66, 2020→65, 2021→72.
Cohort threshold: ≥600 career games, ≥28.0 mean MPG, debut 1984–1995.

---

## pg_b2b_panel.csv / .parquet (DA2)
Back-to-back game classification for every game log row in the PG cohort.

| Column | Type | Description |
|:-------|:-----|:------------|
| player_id | str | BRef player ID |
| game_date | date | Calendar date of game |
| season | int | Season start year |
| opponent | str | Opponent team abbreviation |
| is_b2b | bool | True if previous game was the prior calendar day |
| rest_days | int | Calendar days since last game (0 = same day, 1 = B2B, 2+ = rested) |

Note: rest_days is null for the first game of each season.

---

## pg_quarter_splits.csv / .parquet (DA3)
Per-player per-quarter box score panel for the Stockton PG cohort, 1996–2003 window only
(BRef play-by-play coverage begins 1996-97).

| Column | Type | Description |
|:-------|:-----|:------------|
| player_id | str | BRef player ID |
| player_name | str | Full name |
| season | int | Season start year |
| quarter | str | Q1, Q2, Q3, Q4 |
| ft_pct | float | Free throw percentage |
| ts_pct | float | True shooting percentage |
| ast_tov | float | Assist-to-turnover ratio |
| fga | int | Field goal attempts |
| n_games | int | Games contributing to this cell |
| is_treated | bool | True for Stockton only |

Caveat: Q4 values reflect garbage-time selection bias; starters sit in non-competitive games.
Age-regime caveat: Stockton's window covers ages 34–40 (career decline phase).

---

## pg_cohort_eligibility.csv (DA4)
Every point guard considered for the cohort, with qualification status and exclusion reason.

| Column | Type | Description |
|:-------|:-----|:------------|
| player_name | str | Full name |
| player_id | str | BRef player ID |
| career_span | str | e.g. "1989–2005" |
| total_games | int | Career games played |
| mean_mpg | float | Career mean minutes per game |
| qualified | bool | Met all thresholds |
| exclusion_reason | str | If not qualified: which threshold failed, or "" |

Example exclusion: Terry Porter — mean_mpg 27.8, below 28.0 threshold.
```

---

## Open flags

**A4 permutation output:** `analyze_durability.py` must emit the 5,000 permuted gap values (not just the point estimate and p-value) for the null histogram to render. Check before the dispatch session fires — add `--emit-permutation-null` or equivalent output path if missing.

**DA2 emit step:** Verify that `analyze_durability.py` or a small helper emits the B2B flag panel as a standalone CSV, not just uses it internally. Add an explicit `data/pg_b2b_panel.csv` write if not.
