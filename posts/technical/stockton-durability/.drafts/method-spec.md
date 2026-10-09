---
draft: true
---

# Stockton Durability Study — Method Spec

_Scoping document for "Can We See John Stockton's Heart Rate in the Box Score?" Drafted 2026-10-08._

---

## 1. Research Question

**Does Stockton show a statistically distinguishable resilience-to-workload signal — in durability, late-game efficiency, and fatigue-driven decision-making — compared to a matched cohort of contemporaneous point guards?**

Bayesian framing: the prior is the distribution of those outcomes across comparable PGs controlling for workload; the observation is Stockton's career record; the posterior is a credibility interval on the size of the gap. A large, stable gap is consistent with the physiology claim. A gap near zero or explained by confounds is not.

---

## 2. Comparison Cohort

**Do not pull all ~5K players.** The physiology claim is specific to high-workload, long-career guards operating at peak pace. Scraping everyone dilutes the signal and inflates the computational cost roughly 50×.

**Selection rule:** point guards who debuted between 1984 and 2000, played ≥ 600 career games, and averaged ≥ 28 MPG over their career. This yields roughly 15–25 players and captures the era's pace regime, positional role (continuous-motion guard = most sensitive to recovery), and longevity baseline.

Seed list (illustrative): Isiah Thomas, Kevin Johnson, Tim Hardaway, Gary Payton, Mark Jackson, Terry Porter, Rod Strickland, Muggsy Bogues, Sherman Douglas, Jason Kidd, Steve Nash (overlapping end), Derek Harper. Adjust at scrape time based on career-games filter.

---

## 3. Estimands

| Estimand | Operationalization | Data required | Tractability |
|---|---|---|---|
| E1 — Career durability | Games missed per 82 vs cohort, OLS controlling for MPG and seasons played | Game logs (cheap) | Easy |
| E2 — 4Q FT% degradation | Player's 4Q FT% minus 1Q–3Q FT%, within-season average | Per-game quarter box scores (expensive) | Medium |
| E3 — Fatigue-driven shot selection | 4Q 3PA/FGA and FTA/FGA vs full-game baseline, back-to-back vs rest | Game logs + schedule (cheap) | Easy |
| E4 — Decision-making under fatigue | AST/TOV in 4Q vs full-game, back-to-back vs rest | Quarter box scores (expensive) | Medium-High (requires E2 join) |
| E5 — True shooting late-game | TS% in 4Q vs 1Q–3Q, by rest condition | Quarter box scores (expensive) | High (requires E2+E4 joins + rest-condition merge) |

E1 and E3 are the **primary** estimands: cheap data, clean operationalization, strongest expected effect size. E2/E4/E5 are secondary; pursue only if E1/E3 are positive.

**Within-game vs between-game distinction:** Per-game box scores support only between-game comparisons (rested vs. back-to-back, high-minute vs. normal-minute stretches). Within-game decay (Q1 vs Q4 performance) requires quarter-level box scores or play-by-play. E3 is a between-game estimand; E2/E4/E5 are within-game. Late-game stats carry additional confounders — score margin, intentional fouling in close games, garbage-time lineup changes, and coaches shortening minutes for visibly tired players. FT% (E2) is the least confounded of these because FT shooting is isolated, consistent, and not directly managed by clock or margin decisions; it is the correct starting point for within-game analysis.

---

## 4. Data Pipeline

**Cheap tier — game logs (one page per player-season):**
```
https://www.basketball-reference.com/players/{initial}/{player_id}/gamelog/{year}/
```
Columns used: `Date`, `G`, `MP`, `FTA`, `FTM`, `FGA`, `3PA`, `AST`, `TOV`. Merge key: `(player_id, date)`. Derive rest days from date differences; flag back-to-backs (`rest == 1`).

**Expensive tier — per-game quarter box scores:**
```
https://www.basketball-reference.com/boxscores/{game_id}.html
```
~82 requests per player-season. For a 20-player cohort × 15 seasons = ~24,600 requests. Rate-limit to 3–5 requests/second with `time.sleep`. Cache to parquet by game_id. **Only scrape if E1/E3 justify it.**

Build order: (1) game logs for all cohort players → (2) schedule-derived rest variables → (3) E1 + E3 analysis → (4) if warranted, per-game quarter box scores for Stockton + 3–5 closest comparators → (5) E2/E4/E5.

---

## 5. Statistical Methods

- **E1 (durability):** OLS regression of games-missed-per-82 on `is_stockton`, controlling for career MPG and total seasons. ⚠️ **Inference caveat:** the cohort is selected on ≥600 games (a truncated form of the outcome), so OLS controls do not fix the truncation bias. Instead of bootstrap CIs, report the raw Stockton gap against a permutation/placebo distribution — resample treatment assignment over the cohort N times and report where the observed gap falls in that null distribution. Secondary: Wilcoxon rank-sum on the raw distribution.
- **E3 (shot selection):** Within-player paired differences (back-to-back vs rest) on 3PA/FGA and FTA/FGA. Paired t-test; report effect size (Cohen's d). Stockton's value vs cohort distribution shown as a percentile. ⚠️ **Limitation:** conditioning on playing a B2B selects healthier player-states; the within-player pairing removes stable effects but not state selection. Name this as a study limit; consider a prior-game-minutes covariate or restrict claims to "among games actually played."
- **E2/E4/E5 (quarter splits):** Mixed-effects model: `metric ~ quarter * is_stockton + (1|player_id)`, with rest condition as a covariate. Interaction term `quarter4 × is_stockton` is the estimand. Permutation CIs on the interaction coefficient (same rationale as E1 — n_treated = 1). ⚠️ **Age-regime caveat:** the quarter window (1996–2003) covers Stockton's ages 34–40. A null result in this window does not contradict the peak-workload resilience claim; state this explicitly before reporting.

All reported intervals are permutation-based (treatment reassigned over cohort). No p-value thresholds; report the full null distribution and observed statistic.

---

## 6. Open Questions

**Q1 — Quarter-split data coverage.** BRef seasonal quarter splits exist from ~1996–97; Stockton's early career (1984–96) has no quarter data. Recommendation: clearly label the analysis as covering 1996–2003 (his final 7 seasons) for all quarter-level estimands; treat the durability analysis as covering the full career separately.

Outreach sent attempt 2026-10-09 to Justin Jacobs (Squared Statistics) via squared2020.com; form requires browser submission (agent blocked). Pre-1996 window remains unresolved until reply received. See `.drafts/jacobs_outreach.md` for email draft and block log.

**Q2 — Missed-game attribution.** BRef game logs mark DNP but not reason (injury vs rest vs coach's decision). ⚠️ Rest management barely existed in the 1980s–90s, so "treat all DNPs equally" already systematically penalizes Stockton's comparators less than a modern player would be penalized — the direction of the bias favors Stockton's era. Recommendation: if adding a rest-management sensitivity, specify the extraction method (Spotrac injury reports + targeted news-archive queries) and coverage criteria before running it; otherwise drop the sensitivity and state the directional bias explicitly.

**Q3 — Cohort contamination.** Some PGs in the seed list also had unusually low injury rates (Nash, Kidd). Including them compresses the gap. Recommendation: report results with and without the top-5 durability comparators to show the gap is not an artifact of cohort selection.

**Q4 — Causal language.** The post cannot establish that the heart rate caused the outcomes. Recommendation: frame consistently as "consistent with" and "does not contradict" the physiology claim; never write "proves" or "caused by."

---

## 7. Post Structure

1. **The Claim** — introduce the 35 BPM anecdote and frame the testable question.
2. **Who to Compare Him To** — cohort selection rationale; brief table of the comparison players and their career game totals.
3. **Did He Actually Miss Fewer Games?** — E1 results; histogram of cohort games-missed-per-82 with Stockton marked.
4. **Does He Hold Up Late in Games?** — E3 shot-selection results; if secondary estimands run, E2/E5 here.
5. **Decision-Making Under Load** — AST/TOV back-to-back vs rest (E4 if run, or E3 supplemental).
6. **What the Data Can and Cannot Say** — scope boundary section; explicit caution on causality and unmeasured confounds.
7. **Conclusion** — one paragraph: size of the observed gap, confidence in it, and what would be needed to go further.

---

## 8. Scope Boundary

This post does **not**: verify or challenge the 35 BPM figure (no physiological data); model heart rate or any other biometric directly; claim causality between physiology and outcomes; analyze seasons before 1984–85 (no digital box scores); scrape per-game quarter data for all ~5K NBA players (neither motivated nor tractable); or compare across positions (the claim is position-specific).
