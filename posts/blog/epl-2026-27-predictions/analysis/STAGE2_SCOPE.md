---
draft: true
---

# Stage 2 scope — fit, simulate, horse-race

_Scoping + scaffolding for Stage 2 of the Week-1 overreaction study
(companion to `../method-spec.md`, which is the analysis contract, and
`../data/PANEL_README.md`, the Stage 1 data dictionary). Drafted 2026-09-02.
**Status: scaffolding only.** Every function in this package raises
`NotImplementedError`; nothing has been fitted, simulated, or scored, and no
Stage 1 data has been touched._

## Module map

| Module | Responsibility | Spec section |
|---|---|---|
| `params.py` | Frozen containers: `LinkParams`, `Hyperparams`, `FoldFit`; season constants | Rating framework, Validation |
| `ratings.py` | Fold-internal fits (link μ/ρ/h, K̂, seed w/R_prom, λ); prior ratings (checkpoint 0); fills `prior_strength` / `preseason_tier` / `week1_opponent_tier` | Preseason seed, Prior |
| `estimators.py` | Pooled surprise regression (primary, statsmodels post-local); per-season ridge fit (declared secondary); overreaction ratio | Identification problem; Decisions |
| `checkpoints.py` | `SupremacyTransport` (shared transport) + one builder per checkpoint | Simulation |
| `horse_race.py` | Brier/log-loss/RPS per (season, checkpoint); paired differences, season-block bootstrap, sign test, Holm; reliability curves | Estimand 1, Validation |
| `decay.py` | β_k for k = 2…6 (reversal test), reusing the surprise machinery | Estimand 3 |
| `loso.py` | Outer nested-LOSO driver: `fit_fold` → `evaluate_fold` → `run_loso` → `freeze_outputs` | Validation |

**Deviation from the proposed layout:** one added module, `params.py`. The
proposed five analysis modules all need the same bundle of fitted scalars,
and passing loose dicts invites silent leakage (a fold's λ quietly swapped
for another's). A frozen `Hyperparams` dataclass, produced once per fold by
`loso.fit_fold` and threaded everywhere, makes each fold's fitted state a
single auditable object. It contains no logic — data holders only. Two
smaller signature deviations: `build_prior_ratings` takes `(panel, matches,
season, hyperparams)` rather than the sketched `fold_seasons` argument (the
fold context lives in `hyperparams`; the function needs to know *which*
season's prior to build, not the training list), and `estimators` gains
`build_surprise_frame` as a named step because the decay curve reuses it
with `week = 2…6`. The segmented outcome regression (estimand 4) is *not*
scaffolded here: it runs on the filled panel with standard tools and belongs
to the post's own analysis cells once `fill_panel_priors` lands; scaffolding
it now would freeze a formula the power-ceiling section says must stay
flexible. Flagged rather than silently omitted.

## Data flow

```
data/panel.parquet ──────────────┐
data/matches_all.parquet ─────┐  │
                              ▼  ▼
             loso.run_loso: for each holdout season S
                              │
        ┌─────────────────────┴──────────────────────┐
        │ loso.fit_fold (training = 17 other seasons)│
        │   ratings.fit_link_params   → μ, ρ, h      │
        │   ratings.fit_rational_k    → K̂           │
        │   ratings.fit_seed_params   → w, R_prom    │
        │   ratings.fit_lambda        → λ̂  (inner CV)│
        │   estimators.pooled_surprise_regression    │
        │     on training-season surprise rows → β̂  │
        │   ratings.build_prior_ratings(S) → R_prior │
        └─────────────────────┬──────────────────────┘
                              ▼
        checkpoints: prior = R_prior
                     rational = R_prior + K̂·shock
                     market   = R_prior + β̂·shock
                              ▼  (shared SupremacyTransport, shared link)
        footy_stats.models.simulate.simulate_season  ×3
                              ▼
        horse_race: Brier/log-loss/RPS per (S, checkpoint)
                    → paired diffs, block bootstrap, sign test, Holm
                    → reliability curves (pooled LOSO output)

Full-sample (descriptive, labelled): estimators.pooled_surprise_regression →
reported β̂ + overreaction ratio; decay.fit_decay_curve → β_k;
ratings.fill_panel_priors → panel columns → estimand-4 regressions in the post.
Everything the post renders is frozen via loso.freeze_outputs.
```

## The nested-LOSO harness

Outer loop: one fold per scorable season S (17 or 18 folds pending Q1).
Inner loop, **re-fitted inside every fold on the 17 training seasons**:

| Fitted quantity | Function | Inner criterion |
|---|---|---|
| μ, ρ, h (+ COVID h) | `ratings.fit_link_params` | DC likelihood on training matches |
| K̂ | `ratings.fit_rational_k` (wraps `elo.fit_k`) | sequential predictive log-lik, training seasons in order |
| w, R_prom | `ratings.fit_seed_params` | OOS predictive log-lik of each training season seeded from its predecessor |
| λ̂ | `ratings.fit_lambda` | inner leave-one-*training*-season-out CV (criterion: Q7) |
| β̂ (fold copy) | `estimators.pooled_surprise_regression` | OLS on training-season surprise rows, season-clustered |

**Global (pre-registered, never fitted, shared across folds):** the Shin
de-vig choice (proportional is a labelled sensitivity, not a selected
option — the spec lists "devig choice" as fold-internal, but nothing selects
it empirically, so it is pinned here as a design constant); the Week-1 /
Week-k match definitions; the checkpoint formulas `R_prior + c·shock`; the
K grid and λ/w/R_prom grid *ranges*; simulation replicate count and the
master RNG seed; the points map; the tercile rule; the era indicator
definitions. The COVID flag itself is data; its fitted h magnitude is
fold-internal.

**Two roles for β̂ (an explicit disambiguation of the spec).** The
validation section says β̂ is re-estimated inside each fold — that is the
copy that builds the *market checkpoint*, so no scored season contributes to
its own market arm. But estimands 2 and 3 (the reported ratio and decay
curve) are descriptive full-sample quantities with season-block bootstrap
CIs, not out-of-sample scores; they use the full-sample fit and are labelled
as such. Conflating the two would either leak (full-sample β̂ in the horse
race) or throw away a season of the headline estimate for no inferential
gain (fold β̂ as the reported number).

**Leakage audit per fold:** the holdout's prior may read exactly its Week-1
fixtures and pre-match odds (that is checkpoint 0's definition) and its
predecessor's final table (training data); no fitting step reads the
holdout's results, and nothing anywhere reads the scored season's final
standings before scoring.

## Checkpoints and the shared transport

One class, `checkpoints.SupremacyTransport` (ratings dict + frozen
`LinkParams`), duck-types `simulate_season`'s model contract
(`score_matrix` / `expected_goals` / `match_probs`). All three checkpoints
are instances of the *same* class differing only in the ratings dict —
transport misspecification cancels between arms by construction, and every
probability claim stays relative. The three builders take the identical
fixture list, replicate count, and RNG seed. Posterior arms differ from the
prior only by the scalar under test (K̂ vs β̂) times the same shock vector.

## Estimator placement (locked)

- The pooled surprise regression is **post-local statsmodels code**
  (`smf.ols(...).fit(cov_type="cluster", cov_kwds={"groups": season})`,
  statsmodels 0.14.6): two predictors + clustered SEs exceed
  `footy_stats.stats.regression.fit_ols` by design, and footy-stats is not
  extended for one consumer.
- The per-season ridge fit (`estimators.ridge_postweek1_fit`) is the
  **declared secondary**, run in parallel and reported side by side — its
  under-identification (move ∝ (1 − λ)·residual) is stated wherever it
  appears.

## Spec correction: closing-odds coverage

The method spec anticipated closing lines from ≈2012/13. Verified in the
fetched data (Stage 1): **`b365c*` columns exist from 2019/20 onward only.**
Closing-line analyses are therefore a **7-season refinement** (2019/20–
2025/26), and the pre-closing era — 11 seasons, 2008/09–2018/19 — runs on
B365 *opening* lines throughout (`week1_odds_source == "b365"` for all of
it). Consequences: the prior's "Week-1 closing" refinement and the market
posterior's "Week-2 closing" read are both opening-line quantities for 11 of
18 seasons; the pre/post-PSR contrast partially confounds regime with
instrument (see Q8); and `params.CLOSING_ODDS_SEASONS` pins the boundary in
code.

## Decisions deferred to post-fit (owner's, restated)

1. **Per-season vs pooled framing** of the post's headline — decided after
   seeing how far the ridge and pooled estimators diverge on the real data.
2. **Whether λ shrinkage is defensible** in the ridge secondary (and how
   prominently the λ sensitivity sweep features).

## Open questions for the owner (resolve before implementation)

**Q1 — RESOLVED (2026-09-08): option (a), fetch 2007/08 to seed 2008/09.**
2008/09 has no in-window predecessor. The seed needs last season's
final ratings; 2007/08 is outside the panel. Options: (a) fetch 2007/08
matches solely to seed 2008/09 (one extra `load_matches` call, no panel
change), or (b) drop 2008/09 from the *scored* folds (it still serves as
training data for K̂ and β̂), leaving 17 scored seasons / 340 team-seasons.
The spec's "~300 team-seasons" of pooled LOSO output suggests some drop was
anticipated but matches neither option exactly. Recommendation: (a) — it
preserves the thin pre-PSR era, which option (b) would thin further to 4
scored seasons.

**Q2 — RESOLVED (2026-09-08): option (a), refit the rational benchmark as a
points-shock responder on the DC-supremacy scale** (K̂ and β̂ share units;
ratio is a well-defined elasticity). Original analysis below.
The spec writes
`Δ_rational(i) = K·shock(i)` with shock in *points* units, but
`footy_stats.models.elo` updates on the **win-expectancy shock**
(score ∈ {0, ½, 1} minus expectancy) and K̂ is in **Elo rating points**,
while β̂ is in **DC supremacy (goals) per unit of points shock**. Points
shock is not an affine function of expectancy shock (W/D/L map to 3/1/0
points but 1/½/0 score — the draw breaks proportionality), and the
Elo-supremacy glue (`elo_diff_to_supremacy`) is nonlinear, so "divide β̂ by
K̂" is not yet a defined operation. Options: (a) refit the rational
benchmark as a *points-shock* responder on the supremacy scale (regress the
Elo-implied per-match supremacy move on the spec's shock over training data
— K̂ becomes directly commensurable, cleanest for the ratio, small extra
fit); (b) convert both to a common scale via the local slope of
`elo_diff_to_supremacy` at diff ≈ 0 plus a fitted expectancy-to-points
projection (no refit, two approximations); (c) redefine the rational arm to
use Elo's native shock and convert only the scale (leaves the ratio's
numerator and denominator responding to *different* shock definitions —
not recommended). `estimators.overreaction_ratio` and
`checkpoints.rational_checkpoint` both block on this.

**Q3 — collapsing two coefficients to one β̂.** The regression
`δ(m) ~ shock(home) + shock(away)` yields β̂_home and β̂_away (expected
signs +, −). The spec speaks of one β_market. Options: constrained refit on
the single regressor `shock(home) − shock(away)` (one clustered SE, cleanest),
or report `(β̂_home − β̂_away)/2` with a delta-method SE — either way the
unconstrained fit's symmetry (β̂_home ≈ −β̂_away) should be reported as a
specification check. Recommendation: constrained refit as the headline,
unconstrained as the check.

**Q4 — μ (and ρ, h) for the held-out season.** The spec says "league scoring
rate μ per season", but the fold cannot read the holdout's own scoring rate
(it is a function of the holdout's results). Options: training-season pooled
μ, the predecessor season's μ, or a fitted time trend. Recommendation:
training-pooled with the predecessor-μ as a sensitivity; whatever is chosen
applies identically to all three arms, so the choice cancels to first order
in comparisons — but it should be pinned.

**Q5 — RESOLVED (2026-09-08): option (a), every arm re-simulates all 380
fixtures** (symmetric; score differences reflect ratings only; accepted that
it caps posterior gains). Original analysis below.
Do the posterior arms re-simulate all 380
fixtures, or condition on the 10 played Week-1 results and simulate 370? The
spec's "full 380-fixture season Monte Carlo … at each checkpoint" reads as
all-380 for every arm — symmetric conditioning, so score differences reflect
ratings only, which is the design's point. But then the posterior arms
ignore 10 known results except through the rating shift. Recommendation:
all-380 for all arms (the alternative hands both posteriors a mechanical,
identical information subsidy that muddies the market-vs-prior primary);
needs an explicit owner sign-off since it caps how much *any* posterior can
win by.

**Q6 — Week-k match definition under staggered starts.** Stage 1 defines
Week 1 per team (earliest fixture); Week k inherits "each team's k-th
fixture". In 2011/12 and 2020/21 a match can be the home side's 2nd and the
away side's 3rd. Options: keep per-team-k matches where both teams agree and
drop/flag mismatches (recommended; `build_surprise_frame` carries a
`week_mismatch` flag), or define weeks by calendar round. At stake: a
handful of matches in 2 of 18 seasons.

**Q7 — λ's inner-CV criterion.** "Chosen by inner cross-validation" does not
say what loss. Candidate criteria: (a) predictive log-likelihood of the left-
out training season's *full-season match results* given its λ-blended prior
(recommended — same currency as every other fit, and directly targets "is
this a good preseason rating"), or (b) distance to that season's Week-2 odds
(market-referential, contaminates the prior with the quantity under test —
not recommended).

**Q8 — pre-2019/20 δ instrument.** For 11 seasons, "Week-k closing" is
actually B365 *opening* for the week-k match — posted after Week-1 results
(so δ is still a genuine posterior read) but earlier in each match's own
odds lifecycle, hence noisier and less news-inclusive. β_pre vs β_post
(the PSR-era split) is therefore also an opening-vs-closing instrument
split. Needs a stated decision: accept and caveat (recommended, consistent
with the spec's "era comparison leans descriptive"), or restrict the era
contrast to a same-instrument design (impossible pre-2019 — there is no
closing line to use).

**Q9 — tercile rule for 20 clubs (minor).** 20/3 is not an integer.
Recommendation: prior-rating ranks 1–7 = top, 8–14 = mid, 15–20 = bottom
(7/7/6), pinned as a global constant.

**Q10 — hyperparameter fitting order (minor, implementation).** Sequential
profile fitting (K̂ first on flat 1500 seeds; then w, R_prom given K̂; then
λ given all three) is cheap and stable; a full joint grid over
(K, w, R_prom) is feasible (~20 × ~11 × ~7 sequential replays per fold) and
closes the loop if the profile choice looks binding. Recommendation:
sequential for the build, joint as a one-off check on a single fold.

## Run order (once implemented)

`build_panel.py` (Stage 1, done) → `loso.run_loso` → `horse_race` scoring +
`estimators`/`decay` full-sample estimands → `ratings.fill_panel_priors` →
`loso.freeze_outputs` → post cells read only frozen `data/` frames.
