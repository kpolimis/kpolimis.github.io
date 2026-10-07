"""Shared parameter containers for Stage 2 of the Week-1 overreaction study.

Pure data holders — no fitting logic lives here. Every scalar the method spec
declares "estimated, never guessed" (w, R_prom, K, h, ρ, μ, λ) has exactly one
field in exactly one container, so a LOSO fold's entire fitted state is a
single frozen object that can be audited for leakage.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd


def check_df_schema(df: pd.DataFrame, required: Sequence[str], name: str) -> None:
    """Raise ValueError if ``df`` is missing any required columns or is empty.

    Call this immediately after loading a parquet/CSV at pipeline boundaries
    to surface schema drift early rather than getting a cryptic KeyError deep
    inside an analysis module.

    Args:
        df: The loaded DataFrame.
        required: Column names that must be present.
        name: Human-readable label for the DataFrame (used in error messages).

    Raises:
        ValueError: if any required column is absent or if ``df`` is empty.
    """
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"{name}: missing required columns {missing}")
    if df.empty:
        raise ValueError(f"{name}: DataFrame is empty — pipeline broken")

#: football-data 4-digit season codes covered by the Stage 1 panel, in
#: chronological order (mirrors ``build_panel.SEASONS``; duplicated here so
#: the ``analysis`` package never imports the Stage 1 build module).
SEASONS: list[str] = [
    "0809", "0910", "1011", "1112", "1213", "1314", "1415", "1516", "1617",
    "1718", "1819", "1920", "2021", "2122", "2223", "2324", "2425", "2526",
]

#: Seasons whose match frames carry B365 *closing* odds (``b365c*`` columns).
#: Spec correction: closing lines exist from 2019/20 onward only (7 seasons),
#: not from ≈2012/13 as the method spec anticipated. See STAGE2_SCOPE.md.
CLOSING_ODDS_SEASONS: list[str] = ["1920", "2021", "2122", "2223", "2324", "2425", "2526"]

#: The three rating checkpoints of the triptych, in presentation order.
CHECKPOINTS: tuple[str, str, str] = ("prior", "rational", "market")


@dataclass(frozen=True)
class LinkParams:
    """Frozen Dixon–Coles link parameters for one LOSO fold.

    The link maps a rating difference (goal-supremacy scale) to 1X2
    probabilities via ``footy_stats.models.poisson.supremacy_to_probs``. All
    three fields are fitted on the fold's training seasons only (method spec,
    "Rating framework" and "Validation").

    Attributes:
        total_rate: League scoring rate μ (expected total goals per match)
            used by the DC grid. Fitted on training seasons; how it is carried
            to the held-out season is open question Q4 in STAGE2_SCOPE.md.
        rho: Dixon–Coles draw-correction ρ.
        home_adv: Home advantage h on the supremacy (goal) scale, added to the
            home side before the link is applied.
        covid_home_adv: Replacement h for seasons flagged ``covid_restart``
            (2019/20 run-in, 2020/21), per the spec's season-level
            home-advantage flag. ``None`` means no override.
    """

    total_rate: float
    rho: float
    home_adv: float
    covid_home_adv: float | None = None


@dataclass(frozen=True)
class Hyperparams:
    """Every fold-internal fitted scalar for one LOSO fold.

    One instance is produced per fold by ``loso.fit_fold`` and consumed by
    ``ratings.build_prior_ratings`` and ``checkpoints``. Nothing in this
    container may be computed from the fold's held-out season.

    Attributes:
        regress_weight: Seed carry fraction w (1 keeps last season's rating,
            0 collapses to the league mean).
        promoted_baseline: Flat seed rating R_prom for newly promoted clubs.
        k_rational: Elo K̂ fitted by sequential predictive log-likelihood on
            the training seasons — the rational, results-only benchmark.
            NOTE: in ``footy_stats`` Elo units (rating points per unit of
            win-expectancy shock); commensuration with β̂_market is open
            question Q2 in STAGE2_SCOPE.md.
        lam: Prior-refinement shrinkage λ for the Week-1 MAP fit, chosen by
            inner cross-validation within the training seasons.
        link: The fold's frozen Dixon–Coles link parameters.
    """

    regress_weight: float
    promoted_baseline: float
    k_rational: float
    lam: float
    link: LinkParams


@dataclass(frozen=True)
class FoldFit:
    """Everything fitted inside one LOSO fold, ready to score its holdout.

    Attributes:
        holdout_season: 4-digit code of the season this fold never saw.
        hyperparams: All fold-internal fitted scalars.
        beta_market: β̂_market from the pooled surprise regression fitted on
            the training seasons only (the fold-internal copy used to build
            the market checkpoint; the *reported* β̂ is the full-sample fit —
            see STAGE2_SCOPE.md, "Two roles for β̂").
        k_commensurated: The fold's commensurated rational slope (supremacy
            per unit points-shock, from
            ``estimators.commensurated_rational_slope``) — the coefficient
            for the rational checkpoint. Distinct from
            ``hyperparams.k_rational``, which is in raw Elo units.
        prior_ratings: Per-club prior ratings for the holdout season
            (output of ``ratings.build_prior_ratings``).
    """

    holdout_season: str
    hyperparams: Hyperparams
    beta_market: float
    k_commensurated: float
    prior_ratings: pd.DataFrame
