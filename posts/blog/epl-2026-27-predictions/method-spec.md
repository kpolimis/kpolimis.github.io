# Week-1 Overreaction Study — Method Spec

_Finalized method spec for the EPL 2026/27 predictions post. Drafted 2026-08-22,
the day the season opens (Week 1: 2026-08-22 to 2026-08-24). The post publishes
after the opening weekend; Week-2 closing odds are captured before Week-2
kickoff (on or about 2026-08-29). Companion to
`football/footy-stats/docs/scoping.md` — this doc consumes the same layer
vocabulary (sources / stats / models / cache). Design + documentation only; no
pipeline code is specified here._

## The research question

**Does the betting market overreact to Week 1 of an EPL season?** Thesis of the
post: don't read too much into Week 1.

Bayesian framing. Preseason odds are the market's prior. Week 1 is one weak
observation — 1 of 38 games, ~2.6% of the season's evidence. Week-2 odds are
the market's posterior. A rational updater barely moves after one match. If the
market moves substantially more than a calibrated results-only updater would,
and seasons end near the preseason prior, the Week-1 move was overreaction.

Three objects, one per panel of the triptych:

| Panel | Object | Built from |
|---|---|---|
| Prior | preseason team strength | seed model + Week-1 *closing* odds (pre-result) |
| Rational posterior | prior + justified update | Elo-style update on Week-1 results, K fitted historically |
| Market posterior | prior + market's actual update | Week-2 closing odds, measured as match-level surprise |

## Data

- **Source:** [football-data.co.uk](https://www.football-data.co.uk) EPL match
  CSVs (code E0), via `footy_stats.sources.football_data.load_matches`. Per
  match: result, goals, and 1X2 odds (B365 primary for coverage; Pinnacle as a
  sharp-book sensitivity where present).
- **Odds-coverage caveat (CORRECTED 2026-09-08 from the Stage-1 data pull;
  supersedes the 2026-08-22 estimate).** Closing lines (`B365C`, `PSC`) exist
  only from **2019/20 onward** — 7 seasons, 140 team-seasons — NOT ≈2012/13 as
  an earlier read of the archive assumed. The prior 11 seasons
  (2008/09–2018/19) carry **B365 opening only**, not explicitly labelled
  closing. So: closing-line and sharp-book analyses are a **7-season**
  refinement, and the other 11 seasons run on B365 opening. This compounds
  open-risk #3 and Q8 — the pre-closing contrast is measured on a coarser
  (opening) instrument, so it stays descriptive, and the PSR-era β split
  (β_pre vs β_post) is partly an opening-vs-closing instrument split. The
  pipeline degrades gracefully when B365C/PSC are absent (falls back to B365).
  Verified in Stage 1: `week1_odds_source` = `b365c` for 140 team-seasons,
  `b365` for 220, none missing.
- **Seasons:** 2008/09 through 2025/26 (18 seasons, ≈360 team-seasons, ≈54
  promoted team-seasons before any exclusions). The live 2026/27 season is the
  illustration, not evidence — it has no outcome yet and is scored
  descriptively only.
- **The futures-avoidance rationale, stated honestly.** Historical *match* odds
  are free and clean. Historical *preseason outrights* (title / top-4 /
  relegation futures) are not freely available anywhere. The design therefore
  never needs a posted future: P(top-4) and P(relegation) are **derived** by
  Monte-Carlo simulation from team ratings, and the market's prior is read off
  Week-1 closing lines — which are posted before any ball is kicked and are
  the market's preseason view of those 20 teams. Every derived probability is
  labelled as model output, never presented as a posted price.
- **Reproducibility:** all frames a rendered post uses are written into the
  post's `data/` via `footy_stats.cache.freeze`.

## Rating framework

One rating per team on a log-strength scale, plus home advantage `h`. The
**link** maps a rating difference to 1X2 probabilities through a Dixon–Coles
Poisson model (league scoring rate μ per season, draw-correction ρ). The link
is fitted on training seasons and frozen; de-vigging uses `devig(..., "shin")`
(`stats.odds`, built), with proportional de-vig as a sensitivity.

### Preseason seed

`R_seed(i) = w · R_final(i, last season)` for survivors (regression toward the
league mean at 0); promoted teams get a single baseline `R_prom`. Both `w` and
`R_prom` — along with Elo `K`, `h`, ρ, and the prior-refinement weight λ — are
**estimated** by maximizing out-of-sample predictive log-likelihood on training
seasons, never guessed.

### Prior (checkpoint 0)

Seed refined by Week-1 closing odds: a MAP fit of ratings to the 10 implied
supremacies, shrunk toward the seed with weight λ (chosen by inner
cross-validation, so it is a fitted quantity, not a free knob). The shrinkage
here is legitimate because a *prior* is being measured, not a *move* — and
because the same prior is the baseline for **both** posterior arms, its
residual arbitrariness cancels to first order in every comparison.

### The identification problem, and the estimator that survives it

Week 1 is 10 matches for 20 teams: 10 supremacy observations, 21 parameters,
and the match graph is 10 disconnected pairs. A ridge fit of *post-Week-1*
ratings is under-identified: the estimated market move is mechanically
proportional to (1 − shrinkage weight) × residual, so the overreaction ratio
would be a monotone function of λ — a knob, not a finding. **The primary
estimator is therefore the pooled match-level surprise regression below;** the
ridge-fit per-season posterior is computed in parallel as a declared
comparison, NOT hidden as an appendix. Both are run on the real historical data
and reported side by side, and the *rhetorical* framing of the post — a
per-season "the market moved X after this Week 1" versus a pooled "the market
historically overmoves by factor X per unit of surprise" — is decided only
after seeing how far the two estimators actually diverge (decision deferred to
post-fit, 2026-08-22). The identified estimator measures the market's update at
match level, where it is directly observed:

1. **Week-1 shock** (per team): `shock(i) = points(i, W1) − E[points]`, where
   the expectation comes from the de-vigged Week-1 closing 1X2 of that very
   match. This is a residual against the market's own pre-match expectation —
   it nets out opponent quality, venue, and the market's prior in one step.
2. **Week-2 surprise** (per match): `δ(m) = s_market(m) − s_prior(m)`, the
   Week-2 closing implied supremacy minus the supremacy predicted from prior
   ratings of the two teams plus `h`, both through the frozen link.
3. **Pooled response regression:** across all training seasons,
   `δ(m) ~ shock(home) + shock(away)` (season-clustered errors). A single
   season cannot separate the two teams' moves inside one match; ~18 seasons of
   varying pairings can. The coefficient **β_market** is the market's average
   rating response to one unit of Week-1 shock.
4. **Rational benchmark:** Elo with historically fitted K is, by construction,
   the empirically optimal *results-only* linear response to the same shock:
   `Δ_rational(i) = K · shock(i)`.

**Overreaction ratio = β̂_market / K̂.** Identified, knob-free, and the two
posterior arms for simulation become `R_prior + β̂·shock` (market) versus
`R_prior + K̂·shock` (rational) — they differ only in the scalar under test.
By design this isolates the *Week-1-attributable* component of the market move;
odds movement from transfers and team news is deliberately excluded from the
posterior ratings (see Open risks for where it can still bias β̂).

## Simulation

`models.poisson` (Dixon–Coles) parameterized by rating difference + home
advantage; `models.simulate` runs the full 380-fixture season Monte Carlo
(≥10,000 replicates) → P(top-4) and P(relegation) per team at each checkpoint:
prior, rational posterior, market posterior. The simulation layer is a
**shared transport**: the identical map is applied to all three rating sets,
so transport misspecification cancels in comparisons *between* checkpoints.
Every claim is relative ("post-Week-1 is no better than preseason under the
same transport"), never a claim about the market's absolute calibration —
this is what keeps the exercise a test of the market rather than of our own
rating model. COVID-era seasons (2019/20 behind-closed-doors run-in, 2020/21)
get a season-level home-advantage flag.

## Estimands

1. **Horse race (headline).** Brier score and log-loss of P(top-4) and
   P(relegation) against actual outcomes, at prior vs market posterior vs
   rational posterior, evaluated leave-one-season-out. Overreaction reads as:
   market posterior no better (or worse) than the prior. Scored as paired
   per-season differences with a season-block bootstrap and sign test — never
   pooled team-seasons treated as independent, because each season fixes
   exactly 4 top-4 and 3 relegation slots. Robustness: rank probability score
   over finish positions, which respects the fixed quotas.
2. **Overreaction ratio.** β̂_market / K̂ from the pooled response regression,
   with a season-block bootstrap CI. Ratio ≈ 1: rational. Ratio > 1 *and*
   estimand 1 shows no accuracy gain: overreaction. (The ratio alone is
   descriptive — a rational market with information beyond results can
   legitimately exceed K; the horse race is the decisive evidence.)
3. **Decay curve (reversal test).** Re-run the surprise regression with Week-k
   closing odds against the prior prediction, k = 2…6: β_k traces how much of
   the Week-1-induced move survives. β_k shrinking toward 0 is the market
   itself unwinding the move — the classic reversal signature of overreaction,
   and fully transport-free.
4. **Segmented outcome regression.** `outcome ~ prior_strength + week1_shock +
   indicators` at team-season level (season points as continuous primary;
   made_top4 / relegated as logistic secondaries), key interaction
   `newly_promoted × week1_shock`. If the market prices Week 1 correctly,
   week1_shock earns a coefficient near its Elo-justified weight; a
   near-zero coefficient given the prior says Week-1 moves were noise.

Supporting, narrative-only: a bet-against-the-movers backtest (fade Week-1
overperformers at Week-2+ closing prices). Market-native and transport-free,
but too noisy at this sample size to headline.

## Indicators

| Indicator | Definition | Role |
|---|---|---|
| `week1_shock` | W1 points − market-expected points (primary signal) | regressor |
| `week1_result` | raw W/D/L | descriptive / narrative only |
| `newly_promoted` | promoted this season | regressor + key interaction |
| `week1_opponent_tier` | opponent's prior-rating tercile | robustness check (absorbed by shock) |
| `home_week1` | W1 at home | robustness check (absorbed by shock) |
| `preseason_tier` | prior-rating tercile | stratified descriptives |
| `post_psr` | season ≥ 2013/14 | regime split |
| `psr_enforcement` | season ≥ 2023/24 | nested overlay, descriptive |

`week1_shock` replaces raw `week1_result` as the fitted signal: W/D/L confounds
opponent quality, venue, and scoreline luck, all of which the market-expected
residual removes by construction.

## PSR regime design

Primary split at the 2013/14 PSR **introduction**: pre-era 2008/09–2012/13
(5 seasons) vs post-era 2013/14–2025/26 (13 seasons). Fitted era terms:
`post_psr` main effect, `post_psr × week1_shock`, `post_psr × newly_promoted`,
plus an era split of β_market (β_pre vs β_post). The 2023/24 **enforcement**
era (first points deductions: Everton, Nottingham Forest) is a nested
indicator and case-study overlay only — 3 seasons cannot support a fitted
model. Stated caveat, carried from the design discussion: the pre-era both is
short (5 seasons) and sits in a thinner, less efficient odds market, so the
era comparison leans descriptive.

## Validation

- **Outer loop: leave-one-season-out.** Every scored probability for season S
  comes from a pipeline that never saw S.
- **Inner loop: nested hyperparameter fitting.** All fitted scalars (w, R_prom,
  K, h, ρ, λ, the link, β̂) are re-estimated inside each LOSO fold on the
  remaining 17 seasons. Cheap for a handful of scalars; closes the leak of
  tuning on the evaluation season. LOSO alone is *not* enough — plain LOSO
  with globally fitted hyperparameters would leak.
- **Leakage audit:** the seed uses only last season's table; the link, μ, ρ,
  and devig choice are fold-internal; the promoted baseline excludes the
  evaluated season; no step reads final standings of the scored season.
- **Calibration check.** Brier can reward miscalibrated sharpness, so both
  probability sets get reliability curves before the horse race is read:
  quintile bins over pooled LOSO output (~300 team-seasons, ~60 top-4 and ~45
  relegation positives), season-block bootstrap bands. If either arm is badly
  miscalibrated, that is reported *with* the horse race, not instead of it.
- **Multiple comparisons.** Two pre-registered primaries (Brier difference,
  market posterior vs prior, for top-4 and relegation), Holm-corrected.
  Everything else is labelled secondary or descriptive. Emphasis on interval
  estimates over significance stars throughout.
- **Power ceiling, stated honestly.** ≈54 promoted team-seasons split ~15/39
  across eras, further split by Week-1 result, leaves single-digit cells. The
  fitted model therefore stops at **two-way interactions**; the
  `newly_promoted × week1_shock × post_psr` story is presented as a cell-mean
  table with n's shown — a case study, not an estimate. A minimal-detectable-
  effect statement accompanies every fitted interaction.

## footy-stats work required

| Step | Module | Status |
|---|---|---|
| Match results + closing 1X2, 2008/09–2026/27 | `sources.football_data.load_matches` | **built** (0.1) |
| De-vig closing odds (Shin; proportional sensitivity) | `stats.odds.devig` | **built** (0.1) |
| Odds → implied supremacy (the link) | `models.poisson` | **to build** (0.2) |
| Dixon–Coles match model | `models.poisson` | **to build** (0.2) |
| 380-fixture Monte Carlo → P(top-4), P(relegation) | `models.simulate` | **to build** (0.2) |
| Elo / ratings engine (seed, K-fit, updates) | `models.elo` | **to build** — scoped for 0.3, pulled forward into 0.2 by this post |
| Brier, log-loss, RPS, reliability curves | `stats.calibration` | **to build** (new module, 0.2) |
| Surprise/response regressions | `stats.regression.OLSFit` | **built**; season-clustered SEs are a small extension or post-local code |
| Frozen post data | `cache.freeze` | **built** (0.1) |

## Open risks

Carried forward from the red-team; none silently resolved.

1. **Transfer-window confound.** The summer window closes 2026-09-01 — *after*
   Week 2, in every historical season too. Week-1→Week-2 odds moves mix Week-1
   results with signings and team news. The shock-regression design excludes
   uncorrelated news from the posterior ratings, but if Week-1 losers
   systematically buy (panic signings), β̂_market is biased upward and some
   "overreaction" is rational repricing. No free data source separates these;
   flagged in the post as a limitation.
2. **Elo is a modeling choice of "rational."** Fitted-K Elo is the empirically
   optimal *results-only* updater, but a true Bayesian with outside information
   may move more on genuinely informative results. The ratio is therefore
   framed as "move vs results-justified move," and the horse race — not the
   ratio — carries the overreaction verdict.
3. **Thin pre-PSR era.** 5 seasons, sparser sharp-book coverage. Era contrasts
   are reported with intervals wide enough to be honest, and lean descriptive.
4. **Reliability curves at n ≈ 300.** Quintile bins with bootstrap bands are
   the best available; fine-grained calibration claims are out of reach.
5. **Week-2 odds timing.** Closing lines are captured per match over several
   days; late team news enters heterogeneously. Bookmaker consistency (B365
   primary, Pinnacle sensitivity) bounds but does not remove this.
6. **Single league.** ~18 EPL seasons is one market; the conclusion does not
   automatically travel to other leagues, and the post says so.
7. **Homogeneous-response assumption.** β̂_market pools across teams and
   seasons; heterogeneity (promoted sides, era) is explored only as far as the
   power ceiling allows.

## Decisions (locked 2026-08-22)

- **Market move measured at match level; pooled surprise regression is the
  primary (identified) estimator.** The per-season ridge fit is run in parallel
  as a declared comparison, not an appendix. Both are computed on the real data
  and the post's per-season-vs-pooled framing is chosen after seeing how much
  the two diverge — an empirical decision deferred to post-fit, not pre-committed.
- **Overreaction ratio = β̂_market / K̂.** One identified scalar; both
  posterior simulation arms are `prior + coefficient × shock`.
- **`week1_shock` (market-expected-points residual) is the fitted signal;**
  raw W/D/L is narrative only.
- **Fitted interactions capped at two-way;** the three-way promoted × shock ×
  era story is a labelled case study.
- **Nested LOSO everywhere;** no hyperparameter is fitted on a season it is
  scored against.
- **All probability claims are relative under a shared transport;** the post
  never asserts the market's absolute calibration.

## Decisions (locked 2026-09-08, from the Stage-2 scaffold red-team)

The `analysis/STAGE2_SCOPE.md` scaffold surfaced 10 implementation gaps
(Q1–Q10). The three blocking ones were ruled by the owner; the other seven
stand at the scope doc's recommended defaults unless revisited.

- **Q1 — seed 2008/09 by fetching 2007/08** (one extra `load_matches("0708")`,
  used only to seed the first fold). Keeps all 5 pre-PSR seasons scored; panel
  stays ~360 team-seasons. (The earlier "~300 team-seasons" figure is
  superseded.)
- **Q2 — the overreaction ratio's numerator and denominator are made
  commensurable by refitting the rational benchmark as a *points-shock
  responder on the DC-supremacy scale.*** The spec's `Δ_rational = K·shock`
  cannot use `footy_stats.models.elo.fit_k` directly: `fit_k` responds to
  *win-expectancy* shock (score ∈ {0,½,1}) in Elo points, which is not affine
  in the spec's *points* shock (3/1/0) and lives on a different scale than
  β̂_market (DC supremacy per unit points-shock). Resolution: regress the
  Elo-implied per-match supremacy move on the points-shock over training data,
  so **K̂ and β̂_market share units** and `overreaction ratio = β̂_market / K̂`
  is a well-defined elasticity. Supersedes the bare "β̂_market / K̂" line above.
- **Q5 — every simulation arm re-simulates all 380 fixtures** (prior, rational,
  market), symmetric conditioning. Score differences between checkpoints
  reflect *ratings only*. Accepted trade-off: this caps how much any posterior
  can win by, because no arm gets credit for the 10 played Week-1 results
  except through the induced rating shift — which is precisely the market-test
  design.
