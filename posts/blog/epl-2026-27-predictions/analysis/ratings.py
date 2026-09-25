"""Prior ratings: seed, Week-1 MAP refinement, and fold-internal scalar fits.

Implements the method spec's "Rating framework" — the preseason seed
(w, R_prom), the fold's link (μ, ρ, h), the rational Elo K̂, the shrinkage λ,
and checkpoint 0 (the prior: seed refined by Week-1 closing implied
supremacies). Also fills the three panel columns Stage 1 deliberately left
absent: ``prior_strength``, ``preseason_tier``, ``week1_opponent_tier``.

Every ``fit_*`` function here is fold-internal: it must only ever see a LOSO
fold's training seasons (method spec, "Validation").
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache

import numpy as np
import pandas as pd
from footy_stats.models.elo import EloModel, fit_k, seed_ratings
from footy_stats.models.poisson import (
    DixonColesModel,
    implied_supremacies,
    supremacy_to_probs,
)

from analysis.params import Hyperparams, LinkParams

#: Seasons flagged ``covid_restart`` in the Stage 1 panel (2019/20 run-in
#: behind closed doors, 2020/21). Mirrors ``build_panel._COVID_SEASONS``.
_COVID_SEASONS: frozenset[str] = frozenset({"1920", "2021"})

#: Elo home advantage (rating points) held fixed throughout, matching the
#: ``footy_stats.models.elo`` default used by ``fit_k``.
_ELO_HOME_ADV = 60.0

#: Default candidate grids for the seed fit (w in [0, 1]; R_prom on the Elo
#: scale, spanning "clearly relegation-grade" to "league average").
_DEFAULT_W_GRID: tuple[float, ...] = tuple(np.round(np.linspace(0.0, 1.0, 11), 2))
_DEFAULT_R_PROM_GRID: tuple[float, ...] = tuple(float(r) for r in range(1250, 1525, 25))

#: Default λ grid. λ = 0 (exact fit to the ~10 Week-1 supremacies) is
#: excluded: the MAP system is singular there and the spec calls it
#: under-identified. λ = 1 (keep the seed, ignore Week-1 odds) is allowed.
_DEFAULT_LAM_GRID: tuple[float, ...] = tuple(np.round(np.arange(0.05, 1.0001, 0.05), 2))


# ── Link tables (vectorized supremacy ↔ probs ↔ Elo-diff glue) ───────────────


@lru_cache(maxsize=16)
def _link_tables(
    total_rate: float, rho: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Dense lookup tables for the DC link at (total_rate, rho).

    Returns ``(s_grid, p_home, p_draw, p_away, share)`` where ``share`` is
    the expected home points-share P_home + ½·P_draw (strictly increasing in
    supremacy) — the same identity ``footy_stats.models.elo`` uses to glue
    Elo differences to DC supremacies. Interpolating these tables replaces
    per-call ``brentq`` root-finding in the hot fitting loops.
    """
    span = total_rate * 0.98
    s_grid = np.linspace(-span, span, 1601)
    probs = np.array([supremacy_to_probs(s, total_rate, rho=rho) for s in s_grid])
    p_home, p_draw, p_away = probs[:, 0], probs[:, 1], probs[:, 2]
    share = p_home + 0.5 * p_draw
    return s_grid, p_home, p_draw, p_away, share


def _link_probs(sup: np.ndarray, link: LinkParams) -> np.ndarray:
    """1X2 probabilities (n, 3) for an array of supremacies through the link."""
    s_grid, p_home, p_draw, p_away, _ = _link_tables(link.total_rate, link.rho)
    s = np.clip(np.asarray(sup, dtype=float), s_grid[0], s_grid[-1])
    out = np.column_stack(
        [np.interp(s, s_grid, p_home), np.interp(s, s_grid, p_draw), np.interp(s, s_grid, p_away)]
    )
    return out / out.sum(axis=1, keepdims=True)


def _elo_diff_to_sup(diff: np.ndarray, link: LinkParams) -> np.ndarray:
    """Vectorized ``elo.elo_diff_to_supremacy`` via the share table."""
    s_grid, _, _, _, share = _link_tables(link.total_rate, link.rho)
    e = 1.0 / (1.0 + 10.0 ** (-np.asarray(diff, dtype=float) / 400.0))
    e = np.clip(e, share[0], share[-1])
    return np.interp(e, share, s_grid)


def _sup_to_elo_diff(sup: np.ndarray, link: LinkParams) -> np.ndarray:
    """Vectorized ``elo.supremacy_to_elo_diff`` via the share table."""
    s_grid, _, _, _, share = _link_tables(link.total_rate, link.rho)
    s = np.clip(np.asarray(sup, dtype=float), s_grid[0], s_grid[-1])
    e = np.clip(np.interp(s, s_grid, share), 1e-15, 1.0 - 1e-15)
    return -400.0 * np.log10(1.0 / e - 1.0)


def _home_adv(link: LinkParams, season: str) -> float:
    """Effective supremacy-scale home advantage for one season (COVID-aware)."""
    if season in _COVID_SEASONS and link.covid_home_adv is not None:
        return link.covid_home_adv
    return link.home_adv


def _static_match_loglik(sup: np.ndarray, matches: pd.DataFrame, link: LinkParams) -> float:
    """Log-likelihood of matches' 1X2 outcomes given per-match supremacies."""
    probs = _link_probs(sup, link)
    hg = matches["fthg"].to_numpy(dtype=float)
    ag = matches["ftag"].to_numpy(dtype=float)
    outcome = np.where(hg > ag, 0, np.where(hg == ag, 1, 2))
    picked = probs[np.arange(len(probs)), outcome]
    return float(np.log(np.clip(picked, 1e-12, None)).sum())


# ── Season bookkeeping helpers ───────────────────────────────────────────────


def _season_frames(matches: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Split a combined match frame into per-season frames, date-sorted."""
    out: dict[str, pd.DataFrame] = {}
    for season in sorted(matches["season"].unique()):
        sub = matches.loc[matches["season"] == season]
        out[season] = sub.sort_values("date", kind="mergesort").reset_index(drop=True)
    return out


def _season_clubs(matches: pd.DataFrame) -> dict[str, set[str]]:
    """Season code → set of club ids appearing in that season."""
    return {
        s: set(sub["home_club_id"]) | set(sub["away_club_id"])
        for s, sub in _season_frames(matches).items()
    }


def _season_end_ratings(
    matches: pd.DataFrame, k: float, *, home_adv: float = _ELO_HOME_ADV
) -> dict[str, dict[str, float]]:
    """End-of-season Elo snapshots from one chronological walk.

    Replays every season in ``matches`` in chronological order with a single
    ``EloModel(k, home_adv)`` starting flat at 1500, ratings carried across
    season boundaries exactly as ``footy_stats.models.elo.fit_k`` does, and
    snapshots the ratings dict at each season's end.
    """
    model = EloModel(k=k, home_adv=home_adv)
    snapshots: dict[str, dict[str, float]] = {}
    for season, frame in _season_frames(matches).items():
        for home_id, away_id, hg, ag in frame[
            ["home_club_id", "away_club_id", "fthg", "ftag"]
        ].itertuples(index=False):
            model.update(home_id, away_id, int(hg), int(ag))
        snapshots[season] = dict(model.ratings)
    return snapshots


def _fixture_numbers(season_matches: pd.DataFrame) -> pd.DataFrame:
    """Per-match fixture ordinals: each club's k-th chronologically earliest.

    Args:
        season_matches: One season's matches, reset to a 0..n-1 RangeIndex
            (the returned ``match_idx`` points into that index).

    Returns:
        One row per match: ``match_idx``, ``home_fix``, ``away_fix`` — the
        fixture number (1-based) this match is for the home and away club.
    """
    base = season_matches.reset_index(drop=True).reset_index(names="match_idx")
    home = base[["match_idx", "date", "home_club_id"]].rename(columns={"home_club_id": "club_id"})
    away = base[["match_idx", "date", "away_club_id"]].rename(columns={"away_club_id": "club_id"})
    long = pd.concat([home.assign(is_home=True), away.assign(is_home=False)], ignore_index=True)
    long = long.sort_values(["date", "match_idx"], kind="mergesort")
    long["fix_no"] = long.groupby("club_id").cumcount() + 1
    h = long.loc[long["is_home"], ["match_idx", "fix_no"]].rename(columns={"fix_no": "home_fix"})
    a = long.loc[~long["is_home"], ["match_idx", "fix_no"]].rename(columns={"fix_no": "away_fix"})
    return h.merge(a, on="match_idx", validate="1:1").sort_values("match_idx").reset_index(drop=True)


def _previous_season(matches: pd.DataFrame, season: str) -> str:
    """The season code immediately preceding ``season`` in ``matches``.

    Raises:
        ValueError: when no contiguous predecessor season is present.
    """
    codes = sorted(matches["season"].unique())
    if season not in codes:
        raise ValueError(f"season {season!r} not present in the match frame")
    idx = codes.index(season)
    if idx == 0 or codes[idx - 1][2:4] != season[0:2]:
        raise ValueError(
            f"season {season!r} has no contiguous predecessor in the match frame "
            f"(available: {codes})"
        )
    return codes[idx - 1]


# ── Fold-internal scalar fits ────────────────────────────────────────────────


def fit_link_params(train_matches: pd.DataFrame) -> LinkParams:
    """Fit the fold's frozen Dixon–Coles link (μ, ρ, h) on training matches.

    μ is the league scoring rate, ρ the DC draw correction (both via
    ``footy_stats.models.poisson.DixonColesModel.fit`` on the non-COVID
    training matches), and h the home advantage on the supremacy scale.
    Seasons flagged ``covid_restart`` are excluded from the main fit and
    contribute a separate ``covid_home_adv`` estimate per the spec's
    season-level flag. Per open question Q4 (resolved: training-pooled), the
    single training-era μ is carried unchanged to any held-out season.

    Args:
        train_matches: Tidy match frame for the fold's training seasons only
            (subset of ``matches_all.parquet``, with the ``season`` column).

    Returns:
        The fold's frozen :class:`~analysis.params.LinkParams`.
    """
    covid_mask = train_matches["season"].isin(_COVID_SEASONS)
    main = train_matches.loc[~covid_mask]
    if main.empty:  # degenerate fold; fall back to fitting on everything
        main = train_matches
    model = DixonColesModel.fit(main)
    # At equal strengths (attack = defence = 0) the DC rates are
    # λ_home = exp(μ_log + γ), λ_away = exp(μ_log): total_rate is their sum,
    # and h — home advantage on the supremacy (goal) scale — their difference.
    lam_h0 = float(np.exp(model.mu + model.gamma))
    lam_a0 = float(np.exp(model.mu))
    covid_home_adv: float | None = None
    covid = train_matches.loc[covid_mask]
    if not covid.empty:
        covid_model = DixonColesModel.fit(covid)
        covid_home_adv = float(
            np.exp(covid_model.mu + covid_model.gamma) - np.exp(covid_model.mu)
        )
    return LinkParams(
        total_rate=lam_h0 + lam_a0,
        rho=float(model.rho),
        home_adv=lam_h0 - lam_a0,
        covid_home_adv=covid_home_adv,
    )


def fit_rational_k(train_seasons: list[pd.DataFrame], *, home_adv: float = 60.0) -> float:
    """Fit the rational Elo K̂ on the fold's training seasons.

    Thin wrapper over ``footy_stats.models.elo.fit_k``: replays the training
    seasons in chronological order and picks the K maximizing sequential
    predictive log-likelihood — the spec's empirically optimal results-only
    updater (method spec, "The identification problem", step 4). Runs the
    default coarse grid (2, 4, …, 40) then a ±2, step-0.5 refinement around
    the coarse argmax.

    Unit caveat (open question Q2, resolved): ``footy_stats`` Elo updates on
    the win-expectancy shock (score ∈ {0, ½, 1} minus expectancy), not the
    spec's points shock, and K̂ is in Elo rating points. The overreaction
    ratio therefore uses the *commensurated* rational slope from
    ``estimators.commensurated_rational_slope`` (supremacy per unit points
    shock), not this raw K̂.

    Args:
        train_seasons: One tidy match frame per training season, in
            chronological order (columns ``home_club_id``, ``away_club_id``,
            ``fthg``, ``ftag``).
        home_adv: Elo home advantage in rating points, held fixed during the
            K grid search.

    Returns:
        K̂ in ``footy_stats`` Elo units.
    """
    coarse = fit_k(train_seasons, home_adv=home_adv)
    fine_grid = np.arange(max(0.5, coarse - 2.0), coarse + 2.0 + 1e-9, 0.5)
    return fit_k(train_seasons, grid=fine_grid.tolist(), home_adv=home_adv)


def fit_seed_params(
    train_matches: pd.DataFrame,
    *,
    k_rational: float,
    link: LinkParams,
    w_grid: Sequence[float] | None = None,
    r_prom_grid: Sequence[float] | None = None,
) -> tuple[float, float]:
    """Fit the seed parameters (w, R_prom) on the fold's training seasons.

    For each candidate pair, seed every training season (that has a
    contiguous predecessor inside ``train_matches``) from its predecessor's
    end-of-season Elo ratings — taken from a single chronological Elo walk
    with ``k_rational`` (flat 1500 start, ratings carried across seasons, as
    in ``fit_k``) — via ``footy_stats.models.elo.seed_ratings``. Each seeded
    season is then scored *statically* out-of-sample through the link
    (seed Elo difference → supremacy + h → 1X2 log-likelihood of the full
    season), targeting "is this a good preseason rating", and the pair
    maximizing the summed predictive log-likelihood wins. Fitting is
    sequential per Q10 (resolved): K̂ first, then (w, R_prom) given K̂.

    Args:
        train_matches: Tidy match frame for the fold's training seasons only.
        k_rational: The fold's fitted K̂, used to walk ratings within seasons
            when producing each season's end-of-season ratings.
        link: The fold's frozen link, used to turn rating differences into
            match probabilities for scoring.
        w_grid: Candidate carry fractions in [0, 1]; a sensible default grid
            is chosen when ``None``.
        r_prom_grid: Candidate promoted baselines (Elo scale); default grid
            when ``None``.

    Returns:
        ``(regress_weight, promoted_baseline)`` — the spec's (w, R_prom).
    """
    w_candidates = tuple(w_grid) if w_grid is not None else _DEFAULT_W_GRID
    r_candidates = tuple(r_prom_grid) if r_prom_grid is not None else _DEFAULT_R_PROM_GRID
    snapshots = _season_end_ratings(train_matches, k_rational)
    clubs = _season_clubs(train_matches)
    frames = _season_frames(train_matches)
    seasons = sorted(frames)

    # Precompute per-scoreable-season fixed pieces.
    scoreable: list[dict] = []
    for season in seasons:
        try:
            prev = _previous_season(train_matches, season)
        except ValueError:
            continue
        prev_clubs = sorted(clubs[prev])
        prev_final = pd.DataFrame(
            {"club_id": prev_clubs, "rating": [snapshots[prev][c] for c in prev_clubs]}
        )
        scoreable.append(
            {
                "season": season,
                "frame": frames[season],
                "prev_final": prev_final,
                "promoted": clubs[season] - clubs[prev],
                "h_eff": _home_adv(link, season),
            }
        )
    if not scoreable:
        raise ValueError("fit_seed_params: no training season has an in-frame predecessor")

    best: tuple[float, tuple[float, float]] = (-np.inf, (np.nan, np.nan))
    for w in w_candidates:
        for r_prom in r_candidates:
            total = 0.0
            for item in scoreable:
                seeds = seed_ratings(
                    item["prev_final"],
                    regress_weight=float(w),
                    promoted_baseline=float(r_prom),
                    promoted_ids=item["promoted"],
                )
                frame = item["frame"]
                diff = (
                    frame["home_club_id"].map(seeds).to_numpy(dtype=float)
                    - frame["away_club_id"].map(seeds).to_numpy(dtype=float)
                )
                sup = _elo_diff_to_sup(diff, link) + item["h_eff"]
                total += _static_match_loglik(sup, frame, link)
            if total > best[0]:
                best = (total, (float(w), float(r_prom)))
    return best[1]


def fit_lambda(
    train_matches: pd.DataFrame,
    train_panel: pd.DataFrame,
    *,
    hyperparams_partial: Hyperparams,
    lam_grid: Sequence[float] | None = None,
) -> float:
    """Choose the prior-refinement shrinkage λ by inner cross-validation.

    λ governs how far the Week-1-closing-odds MAP fit pulls prior ratings away
    from the seed (method spec, "Prior (checkpoint 0)"): λ = 1 keeps the seed,
    λ → 0 fits the ~10 implied supremacies exactly (under-identified). The
    inner CV leaves one *training* season out at a time (every training
    season with a contiguous predecessor inside ``train_matches``), builds
    that season's prior at each candidate λ, and — per Q7 (resolved) — scores
    the predictive log-likelihood of the left-out season's **full-season
    match results** given its λ-blended prior, held static through the link.

    Args:
        train_matches: Tidy match frame for the fold's training seasons only.
        train_panel: Panel rows for the same training seasons (supplies Week-1
            match identities and shocks; read only for COVID flags here — the
            Week-1 odds come straight from the match frame).
        hyperparams_partial: Fold hyperparameters fitted so far (w, R_prom,
            K̂, link); its ``lam`` field is ignored.
        lam_grid: Candidate shrinkage weights in (0, 1]; default grid when
            ``None``.

    Returns:
        λ̂ — a fitted quantity, not a free knob.
    """
    candidates = tuple(lam_grid) if lam_grid is not None else _DEFAULT_LAM_GRID
    if any(lam <= 0.0 for lam in candidates):
        raise ValueError("lambda grid must be strictly positive (λ = 0 is under-identified)")
    frames = _season_frames(train_matches)
    totals = dict.fromkeys(candidates, 0.0)
    n_scored = 0
    for season in sorted(frames):
        try:
            club_ids, seed_sup, design, y = _prior_components(
                train_matches, season, hyperparams_partial
            )
        except ValueError:
            continue  # no contiguous predecessor: cannot build this season's prior
        n_scored += 1
        frame = frames[season]
        idx = {c: i for i, c in enumerate(club_ids)}
        hi = frame["home_club_id"].map(idx).to_numpy()
        ai = frame["away_club_id"].map(idx).to_numpy()
        h_eff = _home_adv(hyperparams_partial.link, season)
        for lam in candidates:
            rating = _solve_map(seed_sup, design, y, float(lam))
            sup = rating[hi] - rating[ai] + h_eff
            totals[lam] += _static_match_loglik(sup, frame, hyperparams_partial.link)
    if n_scored == 0:
        raise ValueError("fit_lambda: no training season has an in-frame predecessor")
    return float(max(totals, key=totals.get))


# ── Checkpoint 0: the prior ──────────────────────────────────────────────────


def _prior_components(
    matches: pd.DataFrame, season: str, hyperparams: Hyperparams
) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray]:
    """Season-prior building blocks shared by ``build_prior_ratings`` and λ-CV.

    Returns ``(club_ids, seed_sup, design, y)``: the season's clubs (sorted),
    their seed ratings on the centered supremacy scale, the ±1 Week-1 design
    matrix over those clubs, and the Week-1 implied supremacies net of home
    advantage. Week-1 matches are every match that is *some* team's first
    fixture (the Stage 1 per-team definition, so staggered-start seasons
    contribute 11–12 matches and all 20 clubs are covered).
    """
    prev = _previous_season(matches, season)
    walk_matches = matches.loc[matches["season"] <= prev]
    snapshots = _season_end_ratings(walk_matches, hyperparams.k_rational)
    clubs = _season_clubs(matches.loc[matches["season"].isin([prev, season])])
    prev_clubs = sorted(clubs[prev])
    prev_final = pd.DataFrame(
        {"club_id": prev_clubs, "rating": [snapshots[prev][c] for c in prev_clubs]}
    )
    seeds_elo = seed_ratings(
        prev_final,
        regress_weight=hyperparams.regress_weight,
        promoted_baseline=hyperparams.promoted_baseline,
        promoted_ids=clubs[season] - clubs[prev],
    )
    club_ids = sorted(clubs[season])
    elo = np.array([seeds_elo[c] for c in club_ids], dtype=float)
    # Individual ratings on the supremacy-linked scale: each club's Elo offset
    # from the 20-club mean pushed through the Elo↔DC glue, then re-centered
    # so the league mean sits exactly at 0.
    seed_sup = _elo_diff_to_sup(elo - elo.mean(), hyperparams.link)
    seed_sup = seed_sup - seed_sup.mean()

    frame = _season_frames(matches.loc[matches["season"] == season])[season]
    fix = _fixture_numbers(frame)
    w1_idx = fix.loc[(fix["home_fix"] == 1) | (fix["away_fix"] == 1), "match_idx"].to_numpy()
    w1 = frame.loc[w1_idx]
    sup = implied_supremacies(
        w1,
        hyperparams.link.total_rate,
        rho=hyperparams.link.rho,
        method="shin",
        prefer=("b365c", "b365"),
    )
    usable = sup.notna()
    w1, sup = w1.loc[usable], sup.loc[usable]
    idx = {c: i for i, c in enumerate(club_ids)}
    design = np.zeros((len(w1), len(club_ids)))
    for row, (home_id, away_id) in enumerate(
        zip(w1["home_club_id"], w1["away_club_id"], strict=True)
    ):
        design[row, idx[home_id]] = 1.0
        design[row, idx[away_id]] = -1.0
    y = sup.to_numpy(dtype=float) - _home_adv(hyperparams.link, season)
    return club_ids, seed_sup, design, y


def _solve_map(seed_sup: np.ndarray, design: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:
    """Closed-form MAP/ridge blend of seed ratings and implied supremacies.

    Minimizes ``λ·‖R − seed‖² + (1 − λ)·‖y − X·R‖²``:
    ``(λI + (1 − λ)XᵀX)·R = λ·seed + (1 − λ)·Xᵀy``. Because every design row
    sums to zero, the solution's mean equals the (centered) seed's mean, so
    the league mean stays at 0 by construction.
    """
    if not 0.0 < lam <= 1.0:
        raise ValueError(f"lam must lie in (0, 1], got {lam!r}")
    n = len(seed_sup)
    lhs = lam * np.eye(n) + (1.0 - lam) * design.T @ design
    rhs = lam * seed_sup + (1.0 - lam) * design.T @ y
    return np.linalg.solve(lhs, rhs)


def build_prior_ratings(
    panel: pd.DataFrame,
    matches: pd.DataFrame,
    season: str,
    hyperparams: Hyperparams,
) -> pd.DataFrame:
    """Build one season's prior ratings: seed + Week-1-closing-odds MAP fit.

    Checkpoint 0 of the triptych (method spec, "Prior"). Seeds the season's
    20 clubs from the previous season's end-of-season ratings via
    ``footy_stats.models.elo.seed_ratings`` (promoted clubs at R_prom), then
    refines by a MAP fit to the season's Week-1 implied supremacies
    (``footy_stats.models.poisson.implied_supremacies``, Shin de-vig, closing
    odds preferred with opening fallback), shrunk toward the seed with weight
    ``hyperparams.lam``. Ratings are returned on the supremacy-linked scale
    with the league mean at 0. Per Q1 (resolved), 2008/09 is seeded from the
    separately fetched 2007/08 season, which the caller appends to
    ``matches`` for that one build.

    Args:
        panel: The Stage 1 team-season panel (all seasons; only rows for
            ``season`` and its predecessor are read).
        matches: Combined tidy match frame (``matches_all.parquet`` layout);
            supplies the predecessor season's results for the rating walk and
            this season's Week-1 odds. Must not be used beyond Week 1 of
            ``season`` itself.
        season: 4-digit code of the season whose prior is being built.
        hyperparams: Fold-internal fitted scalars; must come from a fold that
            excludes ``season`` whenever this prior will be scored against it.

    Returns:
        One row per club: ``club_id``, ``seed_rating``, ``prior_strength``
        (the MAP-refined rating — the panel's deferred column).
    """
    del panel  # COVID flags are derived from the season code (mirrors the panel's definition)
    club_ids, seed_sup, design, y = _prior_components(matches, season, hyperparams)
    rating = _solve_map(seed_sup, design, y, hyperparams.lam)
    return pd.DataFrame(
        {"club_id": club_ids, "seed_rating": seed_sup, "prior_strength": rating}
    )


def assign_tiers(prior_ratings: pd.DataFrame) -> pd.DataFrame:
    """Attach within-season prior-rating terciles to a prior-ratings frame.

    Tiers are terciles of ``prior_strength`` within one season's 20 clubs
    (method spec, "Indicators"). Per Q9 (resolved): prior-rating ranks 1–7 =
    ``"top"``, 8–14 = ``"mid"``, 15–20 = ``"bottom"`` (7/7/6); exact ties
    break by frame order (``rank(method="first")``).

    Args:
        prior_ratings: Output of :func:`build_prior_ratings` for one season.

    Returns:
        The input frame plus a ``preseason_tier`` column (categorical:
        ``"top"`` / ``"mid"`` / ``"bottom"``).
    """
    out = prior_ratings.copy()
    rank = out["prior_strength"].rank(ascending=False, method="first")
    tier = np.where(rank <= 7, "top", np.where(rank <= 14, "mid", "bottom"))
    out["preseason_tier"] = pd.Categorical(tier, categories=["top", "mid", "bottom"])
    return out


def fill_panel_priors(
    panel: pd.DataFrame,
    priors_by_season: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Fill the panel columns Stage 1 deferred to the fitted seed/link.

    Joins per-season prior ratings (with tiers) onto the team-season panel,
    adding ``prior_strength``, ``preseason_tier``, and — via each row's
    ``week1_opponent_id`` — ``week1_opponent_tier``. Which fold's priors are
    used (fold-internal vs full-sample) depends on the consumer; for the
    descriptive panel the full-sample fit is used and labelled as such.

    Args:
        panel: The Stage 1 team-season panel.
        priors_by_season: Season code → tier-annotated prior-ratings frame
            (output of :func:`build_prior_ratings` then :func:`assign_tiers`).

    Returns:
        A copy of ``panel`` with the three deferred columns added; Stage 1
        columns and row order are untouched.
    """
    lookup = pd.concat(
        [
            frame.assign(season=season)[["season", "club_id", "prior_strength", "preseason_tier"]]
            for season, frame in priors_by_season.items()
        ],
        ignore_index=True,
    )
    out = panel.merge(lookup, on=["season", "club_id"], how="left", validate="m:1")
    opponent = lookup.rename(
        columns={"club_id": "week1_opponent_id", "preseason_tier": "week1_opponent_tier"}
    )[["season", "week1_opponent_id", "week1_opponent_tier"]]
    out = out.merge(opponent, on=["season", "week1_opponent_id"], how="left", validate="m:1")
    out["preseason_tier"] = pd.Categorical(
        out["preseason_tier"], categories=["top", "mid", "bottom"]
    )
    out["week1_opponent_tier"] = pd.Categorical(
        out["week1_opponent_tier"], categories=["top", "mid", "bottom"]
    )
    return out.set_index(panel.index)
