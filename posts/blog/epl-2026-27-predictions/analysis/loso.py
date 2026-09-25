"""The outer nested-LOSO harness: ratings → checkpoints → simulate → score.

Every scored probability for season S comes from a pipeline that never saw S
(method spec, "Validation"). The *nesting* is the point: plain LOSO with
globally fitted hyperparameters would leak, so every fitted scalar — w,
R_prom, K̂, h, ρ, μ, λ, and the fold's β̂ — is re-estimated inside each fold
on the remaining training seasons. See STAGE2_SCOPE.md for the exact
per-fold-vs-global split.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from footy_stats.cache import freeze
from footy_stats.models.simulate import simulate_season

from analysis.checkpoints import market_checkpoint, prior_checkpoint, rational_checkpoint
from analysis.estimators import (
    build_surprise_frame,
    commensurated_rational_slope,
    pooled_surprise_regression,
)
from analysis.horse_race import collect_scores
from analysis.params import CHECKPOINTS, SEASONS, FoldFit, Hyperparams
from analysis.ratings import (
    _COVID_SEASONS,
    _season_frames,
    assign_tiers,
    build_prior_ratings,
    fit_lambda,
    fit_link_params,
    fit_rational_k,
    fit_seed_params,
)

#: The post's ``data/`` directory (this module lives in ``analysis/``).
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class LosoResult:
    """Everything the LOSO harness produces, for scoring and freezing.

    Attributes:
        fold_fits: One :class:`~analysis.params.FoldFit` per scored season —
            the full leakage-auditable fitted state of each fold.
        sims: Simulated checkpoint probabilities, one row per (season,
            checkpoint, club) with ``p_top4``, ``p_relegation``, ``p_pos_*``,
            ``mean_points``, ``mean_rank``.
        scores: Per-(season, checkpoint) metrics from
            ``horse_race.collect_scores``.
        panel_priors: The panel with ``prior_strength`` / tier columns filled
            (full-sample fit, for descriptives — labelled as such).
    """

    fold_fits: list[FoldFit]
    sims: pd.DataFrame
    scores: pd.DataFrame
    panel_priors: pd.DataFrame


def fit_fold(
    all_matches: pd.DataFrame,
    panel: pd.DataFrame,
    holdout_season: str,
) -> FoldFit:
    """Fit one fold: every hyperparameter, on the 17 training seasons only.

    The inner loop of the nested validation. In order: the link (μ, ρ, h;
    ``ratings.fit_link_params``), K̂ (``ratings.fit_rational_k``), the seed
    pair (w, R_prom; ``ratings.fit_seed_params``), λ by inner
    leave-one-training-season-out CV (``ratings.fit_lambda``), the fold's
    β̂_market (``estimators.pooled_surprise_regression`` on training-season
    surprise rows built with training-fold priors), the commensurated
    rational slope (``estimators.commensurated_rational_slope``), and finally
    the holdout season's prior ratings (``ratings.build_prior_ratings``).
    Leakage audit: no step may read the holdout season beyond its Week-1
    fixtures/odds (the prior is allowed exactly those, per checkpoint 0's
    definition), and no step reads its final standings.

    Args:
        all_matches: Combined tidy match frame — all 18 panel seasons plus
            the 2007/08 seed season (which is not in ``SEASONS`` and is
            therefore excluded from every scalar fit automatically).
        panel: The Stage 1 team-season panel, all 18 seasons.
        holdout_season: 4-digit code of the season this fold must never fit
            on.

    Returns:
        The fold's frozen :class:`~analysis.params.FoldFit`.
    """
    train_seasons = [s for s in SEASONS if s != holdout_season]
    train_matches = all_matches.loc[all_matches["season"].isin(train_seasons)]
    train_panel = panel.loc[panel["season"].isin(train_seasons)]

    link = fit_link_params(train_matches)
    k_rational = fit_rational_k(list(_season_frames(train_matches).values()))
    w, r_prom = fit_seed_params(train_matches, k_rational=k_rational, link=link)
    hp_partial = Hyperparams(w, r_prom, k_rational, float("nan"), link)
    lam = fit_lambda(train_matches, train_panel, hyperparams_partial=hp_partial)
    hyperparams = Hyperparams(w, r_prom, k_rational, lam, link)

    # Training priors for the fold's surprise regression: pass all_matches so
    # 0708 is available for seeding 0809's prior.
    priors = {
        s: assign_tiers(build_prior_ratings(train_panel, all_matches, s, hyperparams))
        for s in train_seasons
    }
    surprise = build_surprise_frame(train_matches, train_panel, priors, link, week=2)
    fit = pooled_surprise_regression(surprise)
    k_commensurated = commensurated_rational_slope(
        train_panel, priors, k_hat=k_rational, link=link
    )

    prior_ratings = assign_tiers(
        build_prior_ratings(panel, all_matches, holdout_season, hyperparams)
    )
    return FoldFit(
        holdout_season=holdout_season,
        hyperparams=hyperparams,
        beta_market=fit.beta_market,
        k_commensurated=k_commensurated,
        prior_ratings=prior_ratings,
    )


def evaluate_fold(
    fold: FoldFit,
    all_matches: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    n_sims: int = 10_000,
    seed: int | None = None,
) -> pd.DataFrame:
    """Simulate and collect one holdout season's three checkpoints.

    Builds the prior / rational / market transports (``checkpoints``) from
    the fold's prior ratings, the holdout's ``week1_shock`` vector, the
    commensurated K̂, and the fold's β̂, then runs
    ``footy_stats.models.simulate.simulate_season`` on the holdout's fixture
    list — identical fixtures and replicate count for all three arms, seeds
    derived deterministically from the shared outer seed. Per Q5 (resolved):
    every arm re-simulates all 380 fixtures, so ``fthg``/``ftag`` are nulled
    even though the historical frame carries them. COVID-flagged seasons
    route the h override.

    Args:
        fold: A fitted fold from :func:`fit_fold`.
        all_matches: Combined tidy match frame (supplies the holdout's
            fixture list).
        panel: The Stage 1 panel (supplies the holdout's shocks and flags).
        n_sims: Monte-Carlo replicates per checkpoint (spec: ≥ 10,000).
        seed: RNG seed; per-checkpoint seeds are ``seed + 0/1/2``.

    Returns:
        One row per (checkpoint, club) for the holdout season, in the
        ``LosoResult.sims`` layout.
    """
    season_matches = all_matches.loc[all_matches["season"] == fold.holdout_season]
    frame = _season_frames(season_matches)[fold.holdout_season]
    fixtures = frame.copy()
    fixtures["fthg"] = np.nan  # Q5: all 380 fixtures re-simulated in every arm
    fixtures["ftag"] = np.nan

    holdout_panel = panel.loc[panel["season"] == fold.holdout_season]
    shocks = holdout_panel.set_index("club_id")["week1_shock"]
    covid_season = fold.holdout_season in _COVID_SEASONS
    link = fold.hyperparams.link

    transports = {
        "prior": prior_checkpoint(fold.prior_ratings, link, covid_season=covid_season),
        "rational": rational_checkpoint(
            fold.prior_ratings, shocks, fold.k_commensurated, link, covid_season=covid_season
        ),
        "market": market_checkpoint(
            fold.prior_ratings, shocks, fold.beta_market, link, covid_season=covid_season
        ),
    }
    parts: list[pd.DataFrame] = []
    for i, checkpoint in enumerate(CHECKPOINTS):
        checkpoint_seed = seed + i if seed is not None else None
        sim = simulate_season(fixtures, transports[checkpoint], n=n_sims, seed=checkpoint_seed)
        tidy = sim.reset_index().rename(columns={"index": "club_id"})
        tidy.insert(0, "season", fold.holdout_season)
        tidy.insert(1, "checkpoint", checkpoint)
        parts.append(tidy)
    return pd.concat(parts, ignore_index=True)


def run_loso(
    all_matches: pd.DataFrame,
    panel: pd.DataFrame,
    *,
    seasons: Sequence[str] | None = None,
    n_sims: int = 10_000,
    seed: int | None = None,
    verbose: bool = False,
) -> LosoResult:
    """Run the full outer LOSO loop and assemble the harness output.

    One fold per scored season: :func:`fit_fold` then :func:`evaluate_fold`,
    scores collected via ``horse_race.collect_scores``. Per Q1 (resolved),
    all 18 panel seasons are scorable because 2007/08 (in ``all_matches``,
    not in ``SEASONS``) seeds 2008/09.

    Args:
        all_matches: Combined tidy match frame, 2007/08 + all 18 seasons.
        panel: The Stage 1 team-season panel.
        seasons: Explicit subset of seasons to score (all of ``SEASONS``
            when ``None``).
        n_sims: Monte-Carlo replicates per (season, checkpoint).
        seed: Master RNG seed; fold ``i`` gets ``seed * 100 + i``.
        verbose: Print per-fold progress lines.

    Returns:
        The assembled :class:`LosoResult`.
    """
    scored = list(seasons) if seasons is not None else list(SEASONS)
    fold_fits: list[FoldFit] = []
    eval_parts: list[pd.DataFrame] = []
    for i, holdout_season in enumerate(scored):
        if verbose:
            print(f"fold {i + 1}/{len(scored)}: holdout={holdout_season} ...", flush=True)
        fold = fit_fold(all_matches, panel, holdout_season)
        fold_seed = seed * 100 + i if seed is not None else None
        eval_df = evaluate_fold(fold, all_matches, panel, n_sims=n_sims, seed=fold_seed)
        fold_fits.append(fold)
        eval_parts.append(eval_df)
        if verbose:
            hp = fold.hyperparams
            print(
                f"  k={hp.k_rational} w={hp.regress_weight} r_prom={hp.promoted_baseline} "
                f"lam={hp.lam} beta={fold.beta_market:.5f} "
                f"k_comm={fold.k_commensurated:.5f}",
                flush=True,
            )
    sims = pd.concat(eval_parts, ignore_index=True)
    sims_map = {
        (season, checkpoint): sub.set_index("club_id")
        for (season, checkpoint), sub in sims.groupby(["season", "checkpoint"], observed=True)
    }
    scores = collect_scores(sims_map, panel)
    panel_priors = pd.read_parquet(_DATA_DIR / "panel_priors.parquet")
    return LosoResult(fold_fits, sims, scores, panel_priors)


def freeze_outputs(result: LosoResult, data_dir: Path) -> None:
    """Freeze every frame the rendered post will read into ``data/``.

    Reproducibility rule (method spec, "Data"): all frames a rendered post
    uses are written via ``footy_stats.cache.freeze`` — ``sims``, ``scores``,
    and a per-fold hyperparameter table recovered from ``fold_fits``.
    ``panel_priors`` was already frozen by Wave 1 and is *not* re-written
    here; its presence is asserted instead.

    Args:
        result: Output of :func:`run_loso`.
        data_dir: The post's ``data/`` directory.
    """
    freeze(result.sims, data_dir, "loso_sims")
    freeze(result.scores, data_dir, "loso_scores")
    fold_params = pd.DataFrame.from_records(
        [
            {
                "holdout_season": fold.holdout_season,
                "total_rate": fold.hyperparams.link.total_rate,
                "rho": fold.hyperparams.link.rho,
                "home_adv": fold.hyperparams.link.home_adv,
                "covid_home_adv": fold.hyperparams.link.covid_home_adv,
                "regress_weight": fold.hyperparams.regress_weight,
                "promoted_baseline": fold.hyperparams.promoted_baseline,
                "k_rational": fold.hyperparams.k_rational,
                "k_commensurated": fold.k_commensurated,
                "lam": fold.hyperparams.lam,
                "beta_market": fold.beta_market,
            }
            for fold in result.fold_fits
        ]
    )
    freeze(fold_params, data_dir, "loso_fold_params")
    panel_priors_path = Path(data_dir) / "panel_priors.parquet"
    if not panel_priors_path.exists():
        raise FileNotFoundError(
            f"expected Wave 1 artifact {panel_priors_path} — run run_wave1.py first"
        )
