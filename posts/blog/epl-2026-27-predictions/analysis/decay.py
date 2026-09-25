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

import pandas as pd

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

    Returns:
        One row per k: ``week``, ``beta_market``, ``se_market`` (clustered),
        ``ci_lo``, ``ci_hi`` (season-block bootstrap), ``n_matches``,
        ``n_seasons``, ``share_closing`` (fraction of matches priced from
        closing lines).
    """
    raise NotImplementedError("Stage 2: decay curve beta_k for weeks 2..6")
