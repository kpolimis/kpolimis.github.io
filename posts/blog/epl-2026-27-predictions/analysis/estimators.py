"""The two market-move estimators and the overreaction ratio.

Primary (identified): the pooled match-level surprise regression
δ(m) ~ shock(home) + shock(away) with season-clustered errors (method spec,
"The identification problem", steps 1–3). Locked decision: this is
**post-local statsmodels code** — ``statsmodels.formula.api.ols(...).fit(
cov_type="cluster", cov_kwds={"groups": ...})`` — NOT an extension of
``footy_stats`` (whose ``fit_ols`` is single-predictor by design).

Secondary (declared, run in parallel, reported side by side): the per-season
ridge fit of post-Week-1 ratings, whose estimated move is mechanically
proportional to (1 − λ) × residual and therefore under-identified on its own.
The per-season-vs-pooled rhetorical framing is decided post-fit.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from footy_stats.models.poisson import implied_supremacies

from analysis.params import LinkParams
from analysis.ratings import (
    _elo_diff_to_sup,
    _fixture_numbers,
    _home_adv,
    _season_frames,
    _solve_map,
    _sup_to_elo_diff,
)


@dataclass(frozen=True)
class SurpriseFit:
    """Result of the pooled surprise regression.

    Attributes:
        beta_home: Coefficient on the home team's Week-1 shock.
        beta_away: Coefficient on the away team's Week-1 shock (expected sign
            negative under a homogeneous response).
        beta_market: The single β̂_market reported and fed to the market
            checkpoint. Per Q3 (resolved): the symmetry-constrained refit on
            the single regressor ``shock(home) − shock(away)``; the
            unconstrained pair is kept as the specification check.
        se_home: Season-clustered standard error of ``beta_home``.
        se_away: Season-clustered standard error of ``beta_away``.
        se_market: Season-clustered standard error of ``beta_market``.
        n_matches: Number of match-level observations pooled.
        n_seasons: Number of season clusters.
        raw: The underlying statsmodels results object, kept for diagnostics
            (typed ``object`` so this module's public surface stays
            statsmodels-free). Here: a dict with keys ``"constrained"`` and
            ``"unconstrained"`` holding both fits.
    """

    beta_home: float
    beta_away: float
    beta_market: float
    se_home: float
    se_away: float
    se_market: float
    n_matches: int
    n_seasons: int
    raw: object


def _odds_source(row: pd.Series) -> str:
    """Which B365 triple prices this row: closing preferred, opening fallback."""
    for prefix in ("b365c", "b365"):
        cols = [f"{prefix}h", f"{prefix}d", f"{prefix}a"]
        if all(c in row.index for c in cols) and not any(pd.isna(row[c]) for c in cols):
            return prefix
    return "none"


def build_surprise_frame(
    matches: pd.DataFrame,
    panel: pd.DataFrame,
    priors_by_season: Mapping[str, pd.DataFrame],
    link: LinkParams,
    *,
    week: int = 2,
) -> pd.DataFrame:
    """Assemble the match-level frame for the surprise regression.

    For each Week-``week`` match m of every season present in
    ``priors_by_season``: δ(m) = s_market(m) − s_prior(m), the de-vigged
    Week-``week`` implied supremacy (``implied_supremacies``, Shin, closing
    preferred / opening fallback) minus the supremacy predicted from the two
    teams' prior ratings plus h through the frozen link; joined with both
    teams' Week-1 shocks from the panel (method spec, steps 1–2). A team's
    Week-k match is its k-th chronologically earliest fixture; a match enters
    when it is Week-``week`` for at least one of its teams, and per Q6
    (resolved) matches whose two teams disagree on k (staggered 2011/12 and
    2020/21 starts) carry ``week_mismatch=True`` rather than being silently
    dropped — the caller decides. Also the workhorse for the decay curve
    (``decay.fit_decay_curve`` calls it with ``week`` = 2…6).

    Args:
        matches: Combined tidy match frame (``matches_all.parquet`` layout).
        panel: The Stage 1 team-season panel (supplies ``week1_shock``).
        priors_by_season: Season code → prior-ratings frame; only these
            seasons enter the output (a LOSO fold passes its training
            seasons, the full-sample estimand passes all).
        link: Frozen link parameters used for s_prior and for
            odds → supremacy on the market side.
        week: Which week's closing odds measure the market posterior.

    Returns:
        One row per Week-``week`` match: ``season``, ``match_idx``,
        ``home_club_id``, ``away_club_id``, ``delta``, ``shock_home``,
        ``shock_away``, ``odds_source``, ``week_mismatch`` (bool flag for
        staggered-start disagreements).
    """
    frames = _season_frames(matches.loc[matches["season"].isin(priors_by_season)])
    rows: list[dict] = []
    for season, frame in frames.items():
        fix = _fixture_numbers(frame)
        sel = fix.loc[(fix["home_fix"] == week) | (fix["away_fix"] == week)]
        sub = frame.loc[sel["match_idx"].to_numpy()]
        s_market = implied_supremacies(
            sub, link.total_rate, rho=link.rho, method="shin", prefer=("b365c", "b365")
        )
        prior = priors_by_season[season].set_index("club_id")["prior_strength"]
        shocks = panel.loc[panel["season"] == season].set_index("club_id")["week1_shock"]
        h_eff = _home_adv(link, season)
        for (_, match), (_, sup_mkt), (_, sel_row) in zip(
            sub.iterrows(), s_market.items(), sel.iterrows(), strict=True
        ):
            home_id, away_id = match["home_club_id"], match["away_club_id"]
            s_prior = float(prior[home_id] - prior[away_id] + h_eff)
            rows.append(
                {
                    "season": season,
                    "match_idx": int(sel_row["match_idx"]),
                    "home_club_id": home_id,
                    "away_club_id": away_id,
                    "delta": float(sup_mkt - s_prior) if pd.notna(sup_mkt) else np.nan,
                    "shock_home": float(shocks.get(home_id, np.nan)),
                    "shock_away": float(shocks.get(away_id, np.nan)),
                    "odds_source": _odds_source(match),
                    "week_mismatch": bool(sel_row["home_fix"] != sel_row["away_fix"]),
                }
            )
    return pd.DataFrame.from_records(rows)


def pooled_surprise_regression(surprise: pd.DataFrame) -> SurpriseFit:
    """Fit δ(m) ~ shock(home) + shock(away) with season-clustered errors.

    The primary, identified estimator of the market's Week-1 response (method
    spec, step 3): pooled across seasons because a single season's 10
    disconnected match pairs cannot separate the two teams' moves. Implemented
    with ``statsmodels.formula.api.ols(...).fit(cov_type="cluster",
    cov_kwds={"groups": surprise["season"]})`` per the locked post-local
    decision — do not route this through ``footy_stats``. Rows flagged
    ``week_mismatch`` (staggered starts) are excluded here — the caller-side
    resolution of Q6 — as are rows with a missing δ or shock. Per Q3
    (resolved), the headline ``beta_market`` comes from the constrained refit
    on the single regressor ``shock(home) − shock(away)``; the unconstrained
    pair (whose symmetry β̂_home ≈ −β̂_away is the specification check) is
    reported alongside.

    Args:
        surprise: Output of :func:`build_surprise_frame` (``week=2``).

    Returns:
        A :class:`SurpriseFit` carrying both raw coefficients, the collapsed
        β̂_market, clustered SEs, and the statsmodels results objects.
    """
    data = surprise.loc[
        ~surprise["week_mismatch"]
        & surprise[["delta", "shock_home", "shock_away"]].notna().all(axis=1)
    ].copy()
    data["shock_diff"] = data["shock_home"] - data["shock_away"]

    unconstrained = smf.ols("delta ~ shock_home + shock_away", data=data).fit(
        cov_type="cluster", cov_kwds={"groups": data["season"]}
    )
    constrained = smf.ols("delta ~ shock_diff", data=data).fit(
        cov_type="cluster", cov_kwds={"groups": data["season"]}
    )
    return SurpriseFit(
        beta_home=float(unconstrained.params["shock_home"]),
        beta_away=float(unconstrained.params["shock_away"]),
        beta_market=float(constrained.params["shock_diff"]),
        se_home=float(unconstrained.bse["shock_home"]),
        se_away=float(unconstrained.bse["shock_away"]),
        se_market=float(constrained.bse["shock_diff"]),
        n_matches=int(constrained.nobs),
        n_seasons=int(data["season"].nunique()),
        raw={"constrained": constrained, "unconstrained": unconstrained},
    )


def ridge_postweek1_fit(
    matches: pd.DataFrame,
    season: str,
    prior_ratings: pd.DataFrame,
    link: LinkParams,
    *,
    lam: float,
) -> pd.DataFrame:
    """Fit one season's post-Week-1 market ratings by ridge (the secondary).

    Ridge/MAP fit of 20 post-Week-1 ratings to the season's ~10 Week-2
    implied supremacies, shrunk toward ``prior_ratings`` with weight ``lam``
    (the same closed-form blend as the prior's own Week-1 refinement). Only
    matches that are Week 2 for *both* clubs enter (the Q6 agreement rule);
    clubs with no such match keep their prior exactly. Declared comparison,
    not an appendix: under-identified on its own (the estimated move is
    mechanically ∝ (1 − λ) × residual, so a per-season overreaction ratio
    would be a monotone function of λ), it is run in parallel with the pooled
    regression and reported side by side; whether λ shrinkage is defensible
    here is a deferred post-fit decision.

    Args:
        matches: Combined tidy match frame.
        season: 4-digit code of the season to fit.
        prior_ratings: That season's prior (output of
            ``ratings.build_prior_ratings``).
        link: Frozen link parameters.
        lam: Shrinkage weight toward the prior (the fold's λ̂, reported
            alongside a λ sensitivity sweep).

    Returns:
        One row per club: ``club_id``, ``prior_strength``,
        ``market_rating_postw1``, ``market_move`` (= post − prior).
    """
    frame = _season_frames(matches.loc[matches["season"] == season])[season]
    fix = _fixture_numbers(frame)
    w2_idx = fix.loc[(fix["home_fix"] == 2) & (fix["away_fix"] == 2), "match_idx"].to_numpy()
    sub = frame.loc[w2_idx]
    s_market = implied_supremacies(
        sub, link.total_rate, rho=link.rho, method="shin", prefer=("b365c", "b365")
    )
    usable = s_market.notna()
    sub, s_market = sub.loc[usable], s_market.loc[usable]

    club_ids = prior_ratings["club_id"].tolist()
    prior = prior_ratings["prior_strength"].to_numpy(dtype=float)
    idx = {c: i for i, c in enumerate(club_ids)}
    design = np.zeros((len(sub), len(club_ids)))
    for row, (home_id, away_id) in enumerate(
        zip(sub["home_club_id"], sub["away_club_id"], strict=True)
    ):
        design[row, idx[home_id]] = 1.0
        design[row, idx[away_id]] = -1.0
    y = s_market.to_numpy(dtype=float) - _home_adv(link, season)
    post = _solve_map(prior, design, y, lam)
    return pd.DataFrame(
        {
            "club_id": club_ids,
            "prior_strength": prior,
            "market_rating_postw1": post,
            "market_move": post - prior,
        }
    )


def commensurated_rational_slope(
    panel: pd.DataFrame,
    priors_by_season: Mapping[str, pd.DataFrame],
    *,
    k_hat: float,
    link: LinkParams,
) -> float:
    """Express the rational Elo updater as supremacy per unit points-shock.

    The Q2 (resolved) commensuration: raw ``fit_k`` K̂ is an Elo-points
    response per unit *win-expectancy* shock, which shares neither scale nor
    shock definition with β̂_market (DC supremacy per unit *points* shock —
    the 3/1/0 points map is not affine in the 1/½/0 score map, and the
    Elo↔supremacy glue is nonlinear). Resolution: compute each team-season's
    Elo-implied Week-1 supremacy move —

        Δsup(i) = g(g⁻¹(R_prior(i)) + K̂·(score(i) − e(i))) − g(g⁻¹(R_prior(i)))

    where g is ``elo_diff_to_supremacy`` at the frozen link, R_prior(i) the
    team's prior rating, e(i) its Elo win expectancy for its Week-1 match
    (from the two prior ratings + h through the same glue), and score(i) ∈
    {1, ½, 0} — then regress Δsup on the spec's Week-1 points shock
    *through the origin* (matching the checkpoint form Δ = c·shock). The
    slope is the commensurated rational response, K̂ on β̂'s scale.

    Args:
        panel: The Stage 1 team-season panel (supplies Week-1 identities,
            results, and shocks).
        priors_by_season: Season code → prior-ratings frame; only panel rows
            for these seasons enter the regression.
        k_hat: Raw Elo K̂ from ``ratings.fit_rational_k``.
        link: Frozen link parameters used for the Elo↔supremacy glue.

    Returns:
        The commensurated rational slope (supremacy per unit points-shock).
    """
    score_map = {"W": 1.0, "D": 0.5, "L": 0.0}
    d_sup: list[float] = []
    shocks: list[float] = []
    for season, prior_frame in priors_by_season.items():
        prior = prior_frame.set_index("club_id")["prior_strength"]
        sub = panel.loc[panel["season"] == season]
        h_eff = _home_adv(link, season)
        for row in sub.itertuples(index=False):
            r_team = float(prior[row.club_id])
            r_opp = float(prior[row.week1_opponent_id])
            # Match supremacy from the home side's perspective, then the
            # team's Elo win expectancy via the shared Elo↔DC glue.
            s_match = (r_team - r_opp if row.home_week1 else r_opp - r_team) + h_eff
            d_match = float(_sup_to_elo_diff(np.array([s_match]), link)[0])
            e_home = 1.0 / (1.0 + 10.0 ** (-d_match / 400.0))
            e_team = e_home if row.home_week1 else 1.0 - e_home
            delta_elo = k_hat * (score_map[row.week1_result] - e_team)
            d_team = float(_sup_to_elo_diff(np.array([r_team]), link)[0])
            moved, base = _elo_diff_to_sup(np.array([d_team + delta_elo, d_team]), link)
            d_sup.append(float(moved - base))
            shocks.append(float(row.week1_shock))
    d_sup_arr, shock_arr = np.asarray(d_sup), np.asarray(shocks)
    ok = np.isfinite(d_sup_arr) & np.isfinite(shock_arr)
    return float(
        (d_sup_arr[ok] @ shock_arr[ok]) / (shock_arr[ok] @ shock_arr[ok])
    )


def overreaction_ratio(beta_market: float, k_hat: float, *, link: LinkParams) -> float:
    """Compute the overreaction ratio β̂_market / K̂ on a common scale.

    Estimand 2 of the method spec. Per Q2 (resolved), ``k_hat`` here MUST be
    the *commensurated* rational slope from
    :func:`commensurated_rational_slope` — supremacy per unit points-shock,
    the same units as β̂_market — NOT the raw Elo-points K̂ from
    ``ratings.fit_rational_k`` (which responds to a different shock on a
    different scale; dividing by it would be dimensionally meaningless).
    Ratio ≈ 1: rational; > 1 with no horse-race accuracy gain: overreaction
    (the ratio alone is descriptive).

    Args:
        beta_market: Collapsed β̂ from :func:`pooled_surprise_regression`.
        k_hat: The commensurated rational slope (supremacy per unit
            points-shock) on the same frozen link as β̂_market.
        link: Frozen link parameters both quantities were expressed through
            (kept in the signature as the unit contract's witness).

    Returns:
        The dimensionless overreaction ratio.
    """
    del link  # both inputs already live on this link's supremacy scale
    if not np.isfinite(k_hat) or k_hat <= 0.0:
        raise ValueError(
            f"k_hat must be a positive, finite commensurated slope, got {k_hat!r}"
        )
    return float(beta_market) / float(k_hat)
