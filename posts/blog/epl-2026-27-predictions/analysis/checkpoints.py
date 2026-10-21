"""Assemble the three rating checkpoints into simulate-ready transports.

The simulation layer is a *shared transport* (method spec, "Simulation"): one
identical ratings → Dixon–Coles map is applied to all three rating sets, so
transport misspecification cancels in comparisons between checkpoints. The
two posterior arms differ from the prior only by ``coefficient × shock`` —
K̂ (rational) versus β̂ (market) — the scalar under test.

``SupremacyTransport`` duck-types the model contract of
``footy_stats.models.simulate.simulate_season`` (``score_matrix`` /
``expected_goals`` / ``match_probs``).
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import numpy as np
import pandas as pd
from footy_stats.models.poisson import _dc_grid

from analysis.params import LinkParams

_MAX_GOALS: int = 10


@dataclass(frozen=True)
class SupremacyTransport:
    """Ratings + frozen link, exposed as a simulate-ready match model.

    Maps a fixture to expected goals through the rating difference
    (home − away + h, with the COVID h override where flagged) and the DC
    link at ``link.total_rate`` / ``link.rho`` — the identical map for every
    checkpoint. Duck-typed for ``simulate_season``.

    Attributes:
        ratings: Club id → rating on the supremacy-linked scale.
        link: The fold's frozen link parameters.
        use_covid_home_adv: Apply ``link.covid_home_adv`` (the simulated
            season carries the ``covid_restart`` flag).
    """

    ratings: dict[str, float]
    link: LinkParams
    use_covid_home_adv: bool = False

    def expected_goals(self, home_id: str, away_id: str) -> tuple[float, float]:
        """Return (home, away) expected goals for one fixture.

        Args:
            home_id: Footy club id of the home side.
            away_id: Footy club id of the away side.

        Returns:
            Expected goals ``(lambda_home, lambda_away)`` summing to the
            link's total rate and differing by the rating-implied supremacy.
        """
        h_eff = (
            self.link.covid_home_adv
            if (self.use_covid_home_adv and self.link.covid_home_adv is not None)
            else self.link.home_adv
        )
        sup = self.ratings[home_id] - self.ratings[away_id] + h_eff
        lam_h = max(0.05, (self.link.total_rate + sup) / 2)
        lam_a = max(0.05, (self.link.total_rate - sup) / 2)
        return (lam_h, lam_a)

    def score_matrix(self, home_id: str, away_id: str) -> np.ndarray:
        """Return the DC scoreline probability grid for one fixture.

        Args:
            home_id: Footy club id of the home side.
            away_id: Footy club id of the away side.

        Returns:
            ``(max_goals + 1, max_goals + 1)`` array of scoreline
            probabilities, home goals on the first axis.
        """
        lam_h, lam_a = self.expected_goals(home_id, away_id)
        return _dc_grid(lam_h, lam_a, self.link.rho, max_goals=_MAX_GOALS)

    def match_probs(self, home_id: str, away_id: str) -> tuple[float, float, float]:
        """Return de-correlated 1X2 probabilities for one fixture.

        Args:
            home_id: Footy club id of the home side.
            away_id: Footy club id of the away side.

        Returns:
            ``(p_home, p_draw, p_away)`` from the scoreline grid.
        """
        grid = self.score_matrix(home_id, away_id)
        n = grid.shape[0]
        idx_h, idx_a = np.triu_indices(n, k=1)
        # triu with home goals on the first axis picks home < away; transpose
        # the roles: home wins live strictly *below* the diagonal.
        p_home = float(grid[idx_a, idx_h].sum())
        p_draw = float(np.trace(grid))
        p_away = float(1.0 - p_home - p_draw)
        return (p_home, p_draw, p_away)


def _ratings_dict(prior_ratings: pd.DataFrame) -> dict[str, float]:
    """Club id → prior_strength lookup from a prior-ratings frame."""
    strength = prior_ratings.set_index("club_id")["prior_strength"]
    return {c: float(strength[c]) for c in prior_ratings["club_id"]}


def _shock_value(shocks: pd.Series, club_id: str) -> float:
    """One club's Week-1 shock, with NaN/missing treated as 0 (warned)."""
    val = float(shocks.get(club_id, np.nan))
    if not np.isfinite(val):
        warnings.warn(
            f"missing week1_shock for {club_id!r}; treating as 0.0",
            stacklevel=3,
        )
        return 0.0
    return val


def prior_checkpoint(
    prior_ratings: pd.DataFrame,
    link: LinkParams,
    *,
    covid_season: bool = False,
) -> SupremacyTransport:
    """Build the prior checkpoint transport (checkpoint 0).

    Ratings are ``prior_strength`` exactly as fitted — the preseason view
    that anchors both posterior arms.

    Args:
        prior_ratings: Output of ``ratings.build_prior_ratings`` for the
            simulated season.
        link: The fold's frozen link parameters.
        covid_season: Whether the simulated season carries the
            ``covid_restart`` flag (routes the h override).

    Returns:
        A transport ready for ``simulate_season``.
    """
    return SupremacyTransport(_ratings_dict(prior_ratings), link, use_covid_home_adv=covid_season)


def rational_checkpoint(
    prior_ratings: pd.DataFrame,
    shocks: pd.Series,
    k_hat: float,
    link: LinkParams,
    *,
    covid_season: bool = False,
) -> SupremacyTransport:
    """Build the rational-posterior transport: R_prior + K̂ · shock.

    The results-only justified update (method spec, step 4), with K̂ converted
    to the supremacy scale under the same commensuration rule as the
    overreaction ratio (open question Q2).

    Args:
        prior_ratings: Output of ``ratings.build_prior_ratings``.
        shocks: ``week1_shock`` per club (index: club id), from the panel.
        k_hat: The fold's fitted rational K̂ (commensurated slope).
        link: The fold's frozen link parameters.
        covid_season: Whether the simulated season carries the
            ``covid_restart`` flag.

    Returns:
        A transport ready for ``simulate_season``.
    """
    prior = _ratings_dict(prior_ratings)
    ratings = {c: r + k_hat * _shock_value(shocks, c) for c, r in prior.items()}
    return SupremacyTransport(ratings, link, use_covid_home_adv=covid_season)


def market_checkpoint(
    prior_ratings: pd.DataFrame,
    shocks: pd.Series,
    beta_market: float,
    link: LinkParams,
    *,
    covid_season: bool = False,
) -> SupremacyTransport:
    """Build the market-posterior transport: R_prior + β̂ · shock.

    The market's actual average update per unit of Week-1 shock, from the
    fold-internal pooled surprise regression. Differs from the rational arm
    only in the scalar — by construction (method spec, "Overreaction ratio").

    Args:
        prior_ratings: Output of ``ratings.build_prior_ratings``.
        shocks: ``week1_shock`` per club (index: club id), from the panel.
        beta_market: The fold's fitted β̂_market.
        link: The fold's frozen link parameters.
        covid_season: Whether the simulated season carries the
            ``covid_restart`` flag.

    Returns:
        A transport ready for ``simulate_season``.
    """
    prior = _ratings_dict(prior_ratings)
    ratings = {c: r + beta_market * _shock_value(shocks, c) for c, r in prior.items()}
    return SupremacyTransport(ratings, link, use_covid_home_adv=covid_season)
