# Visualization Design Review
## World Cup 2026 EPL Post — Against VISUAL_STANDARDS.md, Tufte, Wickham

---

## Thinkers Referenced

- **Tufte** — data-ink ratio, chartjunk, proportional ink (*The Visual Display of Quantitative Information*, 1983)
- **Cleveland** — perceptual hierarchy: position > length > angle > area > color (Cleveland & McGill, 1984 JASA)
- **Wickham / Wilkinson** — grammar of graphics: each aesthetic maps a variable through a declared scale
- **Wilke** — *Fundamentals of Data Visualization* (2019) — most directly actionable modern reference
- **Knaflic** — *Storytelling with Data* — titles state the finding, not the variable

---

## Chart-by-Chart Assessment

### 1. Club Minutes Bar (chart-epl-club-minutes)
**What works**
- Horizontal bars sorted descending — correct for long labels (Cleveland)
- End labels substitute for gridlines (Tufte: reduce non-data ink)
- Interactive tooltips avoid labeling every bar (Knaflic: Goldilocks annotation)

**Issues**
- Title "2026 World Cup: Minutes by EPL Club" describes the data; Knaflic/Wilke standard is the finding: e.g. "Manchester City and Arsenal Sent the Most World Cup Minutes"
- Logo inside bar is redundant with bar color for most clubs (Tufte would call it chartjunk for Arsenal, Chelsea, etc. — only earns its keep for disambiguating red clubs)
- Club colors include 5 distinct reds (Liverpool, Arsenal, Nottm Forest, Southampton, Man United); colorblind simulation not run (VISUAL_STANDARDS §8.2 required)

---

### 2. Nation Stacked Bar (chart-nation-stacked)
**What works**
- Club ordering (sorted by total minutes) is intentional, not alphabetical (Cleveland)
- Standalone legend as a separate vconcat strip is an honest workaround for Vega-Lite's emoji limitations

**Issues — most serious of all charts**
- **Stacked bar with 43 nations violates perceptual hierarchy.** Only the first segment (England) can be compared across clubs with position encoding. All middle and end segments require comparing lengths from non-zero baselines — the least accurate perceptual task (Cleveland §1.4, VISUAL_STANDARDS §5)
- VISUAL_STANDARDS §5 explicitly says: stacked bar appropriate for ≤5 categories; use treemap/sunburst for more
- Tufte's preferred alternative: **small multiples** — one bar per club showing only top-5 nations, faceted. Each sub-chart has a zero baseline and position encoding
- Color scheme (tableau20) has no perceptual ordering; 43 flag emojis in the legend are difficult to scan

**Recommended rework**: normalize to % of each club's total and show only top-5 nations + "Other" (6 stacked segments max). OR switch to a dot plot: clubs on x, one row per nation, dot size = minutes.

---

### 3. EPL Players Bar (chart-players, 60 rows)
**What works**
- Player+flag on y-axis elegantly encodes nationality without a separate legend
- Club logo inside bar provides club identity without needing a second legend

**Issues**
- Wilke's practical guideline: stop at ~20 rows for horizontal bar readability. 60 rows requires a very tall chart and relies on the user scrolling — legibility degrades toward the bottom
- `Player_flag` (name + emoji concatenated string) is a grammar hack; the flag is data that should get its own aesthetic channel (Wickham)
- Colorblind issue: multiple red-bared clubs (Liverpool, Arsenal, etc.) are indistinguishable on the bars; logos partially mitigate but don't eliminate

---

### 4. EPL Position vs WC Minutes Scatter (chart-scatter-position-minutes)
**Strongest chart in the post**
- Position encodes both variables on common scales — highest perceptual accuracy (Cleveland)
- OLS trendline with R²/slope/p in subtitle is the correct place for statistical annotation (reduces chartjunk)
- x-domain extended to [0,21] prevents logo clipping

**Issues**
- Logos as point marks instead of standard shapes violates grammar: mark types should come from a finite, perceivable, mappable set (Wickham). In practice logos work here because they directly label club identity — a legitimate trade-off
- "EPL Position vs. World Cup Minutes (2025/26)" as title is still description, not finding. Consider: "Better EPL Clubs Tended to Send More World Cup Minutes"

---

### 5. G+A per 90 by Club (chart-epl-club-ga-overview)
**What works**
- Single question: which clubs were most efficient?
- Sorted correctly

**Issues**
- Same title format issue (description vs. finding)
- Small sample size problem not addressed in the chart: Newcastle at #1 with very few total minutes looks dominant but is noise. Consider a minimum-minutes filter or an annotation flagging small-sample clubs

---

### 6. G+A per 90 by Player Dropdown (chart-epl-club-ga)
**What works**
- Dropdown is the right interaction here: the question is per-club, not cross-club

**Issues**
- Healy: interactive filtering that requires user action hides data by default — the user must know to check each club. Consider starting with all clubs visible and using the dropdown as a highlight rather than a filter
- Duplicate `add_params(club_sel)` on layered charts caused Altair warning (fixed)

---

## Systemic Issues Against VISUAL_STANDARDS Checklist (§12-13)

| Check | Status |
|---|---|
| Chart answers one question (§1.5, §12) | ✓ mostly — stacked bar tries to answer two |
| Encoding matches task (§5) | ⚠ stacked bar is wrong chart type for 43 categories |
| Color palette colorblind-safe (§8.2) | ✗ not verified; 5 red clubs fail deuteranopia |
| Bar charts include zero baseline (§10.1) | ✓ |
| Axis labels include units (§9.2) | ✓ ("World Cup minutes", "G+A per 90 min") |
| Title states finding not description (§11.2) | ✗ all titles are descriptive |
| Annotation of significant features only (§11.1) | ✓ |
| Caption includes data source (§12) | ✓ footnote |
| Categorical variables sorted intentionally (§13) | ✓ sorted by value throughout |
| Direct labels instead of legend for ≤5 series (§11.2) | ⚠ stacked bar legend has 43 entries |

---

## Priority Fixes (Highest ROI)

1. **Nation stacked bar**: Limit to top-5 nations + Other (6 segments). Transforms a perceptually broken chart into a readable one. (High impact, medium effort)
2. **Colorblind check**: Run Coblis or `colorspace::cvd_emulator()` on the multi-red club bars. Add logo disambiguation note in methodology. (Low effort, compliance)
3. **Chart titles**: Change from description to finding. One-line edits. (Low effort)
4. **Small-sample caveat**: Add annotation on G+A chart flagging clubs with <200 WC minutes as noisy. (Low effort)

---

*Written 2026-07-24. Source: VISUAL_STANDARDS.md at `/Users/kivan/repos/incubator/mgmt/VISUAL_STANDARDS.md`.*
