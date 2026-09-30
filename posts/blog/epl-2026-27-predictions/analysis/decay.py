"""The decay curve: does the market itself unwind the Week-1 move?

Estimand 3 (the reversal test): re-run the surprise regression with Week-k
closing odds against the *same* prior prediction, k = 2…6. β_k traces how
much of the Week-1-induced move survives; β_k shrinking toward 0 is the
market unwinding it — the classic reversal signature of overreaction, and
fully transport-free. Reuses ``estimators.build_surprise_frame`` /
``estimators.pooled_surprise_regression`` with the ``week`` argument.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf

from analysis.estimators import build_surprise_frame, pooled_surprise_regression
from analysis.params import LinkParams

#: Default weeks for the decay curve (k = 2 is the headline β̂_market itself).
DECAY_WEEKS: tuple[int, ...] = (2, 3, 4, 5, 6)


def fit_decay_curve(
    matches: pd.DataFrame,
    panel: pd.DataFrame,
    priors_by_season: Mapping[str, pd.DataFrame],
    link: LinkParams,
    *,
    weeks: Sequence[int] = DECAY_WEEKS,
    n_boot: int = 10_000,
    seed: int = 42,
) -> pd.DataFrame:
    """Fit β_k for each week k: the surprise regression against Week-k odds.

    For each k, builds the match-level frame with
    ``estimators.build_surprise_frame(..., week=k)`` — δ measured from Week-k
    closing (2019/20+) or opening (earlier) lines against the frozen-prior
    prediction — and fits ``estimators.pooled_surprise_regression``. A
    descriptive full-sample estimand (it is never scored out-of-sample), so
    it uses the full-sample priors and link with season-block bootstrap CIs;
    see STAGE2_SCOPE.md, "Two roles for β̂". The pre-2019/20 instrument
    caveat (open question Q8) applies with increasing force as k grows.

    Args:
        matches: Combined tidy match frame (``matches_all.parquet`` layout).
        panel: The Stage 1 team-season panel (supplies ``week1_shock``).
        priors_by_season: Season code → prior-ratings frame (full-sample
            fit for the descriptive curve).
        link: Frozen link parameters (full-sample fit).
        weeks: Which weeks k to trace.
        n_boot: Season-block bootstrap replicates per k.
        seed: RNG seed for the bootstrap (one stream across all k).

    Returns:
        One row per k: ``week``, ``beta_market``, ``se_market`` (clustered),
        ``ci_lo``, ``ci_hi`` (season-block bootstrap), ``n_matches``,
        ``n_seasons``, ``share_closing`` (fraction of matches priced from
        closing lines).
    """
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    for week in weeks:
        surprise = build_surprise_frame(matches, panel, priors_by_season, link, week=week)
        # Mirror pooled_surprise_regression's row filter so share_closing and
        # the bootstrap see exactly the rows the full-sample fit uses.
        clean = surprise.loc[
            ~surprise["week_mismatch"]
            & surprise[["delta", "shock_home", "shock_away"]].notna().all(axis=1)
        ].copy()
        clean["shock_diff"] = clean["shock_home"] - clean["shock_away"]
        # share_closing is ~0.39 and constant across all k: odds_source is
        # week-invariant (same match, same source). Pre-2019/20 rows use
        # opening-line fallbacks (B365, not b365c) regardless of k. This
        # fraction is descriptive only; it does not affect any model parameter.
        share_closing = float((clean["odds_source"] == "b365c").mean())

        fit = pooled_surprise_regression(surprise)

        seasons = clean["season"].unique()
        boot_betas = np.empty(n_boot)
        for b in range(n_boot):
            pick = rng.choice(seasons, size=len(seasons), replace=True)
            resample = pd.concat(
                [clean.loc[clean["season"] == s] for s in pick], ignore_index=True
            )
            result = smf.ols("delta ~ shock_diff", data=resample).fit()
            boot_betas[b] = float(result.params["shock_diff"])

        rows.append(
            {
                "week": int(week),
                "beta_market": fit.beta_market,
                "se_market": fit.se_market,
                "ci_lo": float(np.percentile(boot_betas, 2.5)),
                "ci_hi": float(np.percentile(boot_betas, 97.5)),
                "n_matches": fit.n_matches,
                "n_seasons": fit.n_seasons,
                "share_closing": share_closing,
            }
        )
    return pd.DataFrame.from_records(rows)
