# EPL Week-1 Overreaction — Session Handoff (2026-09-08)

Autonomous work done while Kivan ran errands. **Nothing committed. Stage 2 not
implemented** (held at scaffold per your directive). Three things below:
(1) Stage-1 verification, (2) the 7 open Q's with recommendations, (3) commit
drafts.

---

## 1. Stage 1 panel — independently verified from scratch ✅

I rebuilt the panel's key quantities from raw `matches_all.parquet` (not from the
build script) and diffed against the frozen `data/panel.parquet`:

| Check | Method | Result |
|---|---|---|
| `week1_expected_points` | Re-de-vigged each team's W1 closing/opening 1X2 with Shin, recomputed `3·p_win + 1·p_draw` with independent home/away perspective | **max abs diff 0.0** (360/360) |
| `week1_shock` | `points − expected`, independent | **max abs diff 0.0** |
| `week1_points` | Recomputed from goals, both perspectives | **0 mismatches** |
| `week1_odds_source` | Independent b365c→b365 fallback logic | **0 mismatches** |
| `final_points` / `final_position` | Rebuilt all 18 standings from scratch (pts→GD→GF) | **0 mismatches** |
| `newly_promoted` | Independent set-difference vs prior season | **0 mismatches** |
| External tables | Liverpool 24/25 (84, 1st) · Leicester 15/16 (81, 1st) · Man City & Man Utd 11/12 (both 89; City 1st on GD) | **all match** |
| Staggered starts | 11/12 (London riots) & 20/21 (COVID) resolve to 11 & 12 opener-containing matches; every team still gets its true earliest fixture | **handled correctly** |

**Verdict: the panel is trustworthy as the Stage-2 foundation.** The home/away
perspective — the most likely place for a silent flip — reproduces exactly.

**Bonus finding:** `matches_all.parquet` also carries Pinnacle columns
(`psh/psd/psa` opening, `psch/pscd/psca` closing), not just B365. The panel's
`week1_odds_source` only tracks B365, but Pinnacle is available for the
sharp-book sensitivity the spec calls for — worth wiring into Stage 2's
`prefer=("psc","ps","b365c","b365")` sensitivity pass.

---

## 2. Open questions Q3–Q10 (the 3 blockers Q1/Q2/Q5 are already locked)

My independent read of "does this actually matter," with a recommended default.
**None blocks the build** — they need a yes/no, not a discussion.

| Q | Decision | Recommended | Does it matter? |
|---|---|---|---|
| **Q3** | Collapse β̂_home, β̂_away → one β̂ | Constrained refit on `shock(home) − shock(away)`; report unconstrained symmetry as a spec check | **Medium.** Defines the headline scalar. Recommendation is clean; low regret. |
| **Q4** | μ, ρ, h for the held-out season | Training-pooled, predecessor-season as sensitivity | **Low.** Applies identically to all 3 arms, cancels to first order in comparisons. |
| **Q6** | Week-k definition under staggered starts | Per-team-k, flag+drop mismatches (`week_mismatch`) | **Low.** A handful of matches in 2 of 18 seasons; affects decay curve only. |
| **Q7** | λ's inner-CV loss | Predictive log-lik of the left-out training season's full results (NOT distance to its Week-2 odds — that contaminates the prior with the quantity under test) | **Medium.** Option (b) would bias the overreaction finding toward zero. Recommend (a) firmly. |
| **Q8** | Pre-2019/20 δ uses B365 *opening* | Accept + caveat; β_pre vs β_post is partly an opening-vs-closing instrument split | **Medium (honesty, not code).** Already flagged in the spec correction. No same-instrument alternative exists pre-2019. |
| **Q9** | Tercile rule for 20 clubs | ranks 1–7 / 8–14 / 15–20 (7/7/6), pinned constant | **Cosmetic.** |
| **Q10** | Hyperparameter fitting order | Sequential profile (K̂ → w,R_prom → λ); joint grid as a one-fold check | **Low.** Implementation detail; sequential is stable. |

**My suggestion:** accept all seven recommendations as-is. The only two with
real inferential teeth are **Q7** (get the λ criterion right — it protects the
headline) and **Q8** (a disclosure, already handled). The rest are low-regret
defaults.

---

## 3. Commit-message drafts (NOT committed — ready when you say go)

Everything is untracked. Two natural commits:

**A. footy-stats 0.2 (repo `football/`, whole `footy-stats/` untracked):**

```
feat(footy-stats): computational engine — models, sources, calibration (0.2)

Companion to footy (identity). Adds data acquisition + stats/models that
footy refuses to hold: models.poisson (Dixon–Coles MLE + odds↔supremacy
link), models.elo (seed/fit_k/glue), models.simulate (380-fixture MC →
P(top4)/P(relegation)), stats.calibration (brier/log_loss/rps/reliability),
plus sources.football_data and stats.{odds,rates,regression,standardize}.
113 tests, ruff clean.
```

**B. EPL post Stage 1 + Stage 2 scaffold (repo `kpolimis.github.io/`,
`posts/blog/epl-2026-27-predictions/`):**

```
feat(epl-post): Week-1 overreaction study — Stage 1 panel + Stage 2 scaffold

Reangles the 2026/27 predictions post into a Bayesian Week-1-overreaction
study. Stage 1: build_panel.py downloads 18 seasons (E0, 2008/09–2025/26),
freezes match frames, and builds a 360-row team-season panel (week1_shock =
points − de-vigged W1-closing expected points, the primary signal). Stage 2:
analysis/ scaffold (ratings/estimators/checkpoints/horse_race/decay/loso
stubs) + STAGE2_SCOPE.md with the nested-LOSO design and locked decisions.
Consumes footy_stats. No analysis implemented yet.
```

Note: the old `index.qmd` (de-vig futures post) is unchanged and still the
draft body — the Stage-2 numbers feed the rewrite later. You may want the
Stage-1 and Stage-2-scaffold commits split, and to decide whether `data/`
parquet is committed or `.gitignore`d (it's regenerable via `build_panel.py`).

---

## Next step

On your go: implement Stage 2 per the scaffold (delegate to Fable 5, I verify
independently). Until then, everything holds here.
