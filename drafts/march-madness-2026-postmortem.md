Title: March Madness 2026: What My Model Got Wrong and Why It Matters
Date: 2026-05-05
Category: Sports
Tags: machine-learning, sports-analytics, march-madness, ncaa, lightgbm, kaggle, postmortem
Slug: march-madness-2026-postmortem
Summary: I entered the 2026 Kaggle March Madness competition with a LightGBM ensemble, picked Florida to cut down the nets, and watched them exit in the Round of 32. Here's what the model missed, what the leaderboard winners did differently, and what I'm building for 2027.

---

Every March I tell myself the same thing: this year the model will be different. Systematic. Reproducible. No gut feelings, no recency bias, no "they just feel like a Final Four team." Just clean features, a well-calibrated ensemble, and probability estimates that actually mean something.

This year I submitted. Florida was my champion pick. They lost in the Round of 32.

This post is the postmortem I owe myself — and anyone who follows reproducible sports analytics seriously.

---

## The Setup

The [Kaggle March Madness competition](https://www.kaggle.com/competitions/march-machine-learning-mania-2026) asks you to submit win probabilities for every possible matchup in the tournament, not just your bracket. The scoring metric is Brier score — your average squared error between predicted probability and binary outcome. This matters: predicting 0.9 confidence on a loss hurts more than predicting 0.6 on the same loss.

My pipeline, which lives in [`sports-ml`](https://github.com/kivanpolimis/sports-ml), follows this architecture:

```
Raw Data (KenPom, HerHoopStats, Sports-Reference, Odds API)
    ↓  ETL pipelines (BaseETL pattern, SQLite)
Cleaned Features
    ↓  LightGBM + XGBoost + Random Forest ensemble
    ↓  Expanding-window cross-validation (no data leakage)
    ↓  Isotonic probability calibration
Calibrated win probabilities → Kaggle submission CSV
```

The expanding-window CV is the piece I'm most proud of conceptually. For any given tournament year, I train only on prior years. No peeking. The calibration step maps raw model scores to actual win frequencies, which matters enormously for a Brier score competition where overconfidence is penalized.

Florida had the highest championship probability in my model at roughly 18%. The second-highest team was around 12%. I wasn't hedging — I was making a statement.

---

## What Happened

Florida lost to a double-digit seed in the Round of 32. Not a close game. The kind of loss that makes you question whether you understand basketball at all.

Here's the run history from the submission:

| Model Run | Val Brier Score | Florida P(Champion) | Final Round |
|---|---|---|---|
| v1 (baseline LGB) | 0.218 | 0.14 | — |
| v2 (+ calibration) | 0.201 | 0.16 | — |
| v3 (+ HerHoopStats) | 0.196 | 0.18 | Round of 32 |

My final Brier score on the public leaderboard placed me in the middle of the pack. Not embarrassing, but not close to the top.

---

## The Postmortem

### Problem 1: Florida Was a Paper Tiger in the Features

My model loved Florida for reasons that are entirely rational in the regular season and nearly meaningless in a one-game elimination format.

KenPom metrics reward consistent efficiency over 30+ games. Florida had elite adjusted efficiency margins, strong tempo-adjusted offense, and a solid defensive profile. On paper, they looked like a machine. What the features couldn't capture:

- **Injury status at tournament time.** Efficiency metrics are backward-looking. A key player nursing a knee injury in March will drag numbers that were computed over a full season.
- **Schedule strength volatility.** SEC play this year was top-heavy. Florida's numbers were inflated by beating mediocre opponents repeatedly before a few marquee wins.
- **Three-point variance in single-elimination.** One bad shooting night ends your season. My model had no tournament-context features — no "how does this team perform when the variance is highest?"

### Problem 2: Brier Score Optimization Is Not the Same as Bracket Optimization

I trained to minimize squared error across all possible matchups. But Florida's early exit specifically hurt because I had them at 18% for the championship, meaning I was implicitly confident they'd survive early rounds. A Brier-optimal model might spread probability mass more evenly across strong teams rather than concentrating it on one.

The top Kaggle competitors I examined after the competition consistently used **ensembles of diverse models with different prior assumptions** — some KenPom-heavy, some betting-market-derived, some purely historical seed-based. Diversification of prior beliefs, not just of model architectures.

### Problem 3: The Calibration Was Wrong at the Tails

My isotonic calibration improved overall Brier scores in cross-validation, but calibration on historical data doesn't guarantee calibration in the current year if the tournament has unusual upset rates. 2026 had the most first-round upsets since 2023. My model's calibration curves, fit on prior years, systematically underestimated upset probability.

The fix isn't complicated — it's recalibrating on a rolling window of recent tournaments and potentially shrinking toward a seed-based prior — but I didn't have it implemented.

---

## What the Leaderboard Winners Did Differently

I looked at the top-5 submissions post-competition. A few patterns:

**1. Market-implied probabilities as features.** Several winners incorporated pre-tournament betting lines. The market aggregates information — injuries, insider knowledge, recency bias adjustments — that statistical models miss. This isn't cheating; it's acknowledging that the market is a strong prior.

**2. Tournament-specific historical features.** Winners built features like "how does this seed perform in this round historically," "what's this program's tournament experience index," and "how volatile is this team's three-point attempt rate." These are not KenPom features. They're tournament-context features.

**3. Heavily calibrated ensembles with explicit uncertainty.** The winning submission had a notably flatter probability distribution than mine. The champion pick was around 11% — not 18%. When the true uncertainty is high, spreading probability mass is the correct Brier-optimal strategy.

---

## Would Past Winners Have Done Better This Year?

I ran several historical winning strategies (approximated from published notebooks) against this year's tournament results. Findings:

- **Seed-only baseline** (a 5-minute implementation) outperformed roughly 40% of the competition, including me in a few matchup-specific slots. This is a useful calibration on model complexity hubris.
- **2023 winner's approach** underperformed significantly this year — they had been tuned for a lower-upset environment. A model calibrated well for 2023 is not necessarily well-calibrated for 2026.
- **2021 winner's approach** fared best — they had more conservative champion priors and heavier seed-based regularization.

The lesson: March Madness models that work across years are more conservative than you'd like them to be in any given year.

---

## What I'm Building for 2027

The `sports-ml` repo now has a roadmap item for next year's competition. Key additions:

```python
# New feature categories for v4
TOURNAMENT_CONTEXT_FEATURES = [
    "seed_round_historical_win_rate",
    "program_tournament_experience_index",
    "three_point_attempt_rate_volatility",
    "betting_market_implied_probability",
    "injury_adjusted_efficiency_delta",
]

# Calibration update
CALIBRATION_STRATEGY = "rolling_3yr_tournament_isotonic_with_seed_shrinkage"
```

I'm also wiring up the NBA prediction side of the pipeline, which was a stub this year. The ETL patterns and base model architecture are in place — the work is feature engineering.

---

## Closing Thought

The value of submitting to Kaggle competitions isn't the leaderboard rank. It's the forced discipline of committing to predictions before outcomes are known, then doing an honest postmortem when you're wrong.

My model had principled reasons for picking Florida. Those reasons were wrong. Understanding exactly *why* they were wrong — not just that they were wrong — is what turns this from a failed bracket into a better model.

The notebook is in the repo. The data is public. Run it yourself.

---

*The `sports-ml` repository, including the march_mania_2026.ipynb notebook, feature pipeline, and calibration code, is [available on GitHub](https://github.com/kivanpolimis/sports-ml).*
