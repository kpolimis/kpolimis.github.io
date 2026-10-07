"""Wave 1 driver: full-sample descriptive fits for the Week-1 overreaction study.

Runs the STAGE2_SCOPE "Full-sample (descriptive, labelled)" path — NOT the
nested LOSO (that is Wave 2). Every fitted scalar here is a full-sample
quantity and is labelled as such wherever it is reported.

Steps (results written to disk incrementally, so a partial run still leaves
usable artifacts):
    1. Fit the link (μ, ρ, h + COVID h), K̂, (w, R_prom), λ̂ on all 18 seasons.
    2. Build prior ratings for every season (2008/09 seeded from a separately
       fetched 2007/08 per Q1) and fill the panel's deferred columns →
       ``data/panel_priors.parquet``.
    3. Build the Week-2 surprise frame; pooled surprise regression →
       β̂_market (constrained headline + unconstrained symmetry check),
       season-clustered SEs.
    4. Per-season ridge post-Week-1 fits → per-season implied response and
       the pooled-vs-ridge divergence summary.
    5. Commensurated rational slope (Q2) and the overreaction ratio.
    6. Sanity gates + headline summary; scalars in ``data/wave1_results.json``.

Run from the post directory:

    python3 run_wave1.py
"""

from __future__ import annotations

import dataclasses
import json
import logging
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
from analysis.estimators import (
    build_surprise_frame,
    commensurated_rational_slope,
    overreaction_ratio,
    pooled_surprise_regression,
    ridge_postweek1_fit,
)
from analysis.params import SEASONS, Hyperparams, check_df_schema
from analysis.ratings import (
    _season_frames,
    assign_tiers,
    build_prior_ratings,
    fill_panel_priors,
    fit_lambda,
    fit_link_params,
    fit_rational_k,
    fit_seed_params,
)
from footy_stats.sources.football_data import load_matches

logger = logging.getLogger(__name__)

POST_DIR = Path(__file__).resolve().parent
DATA_DIR = POST_DIR / "data"
RESULTS_PATH = DATA_DIR / "wave1_results.json"

_MATCHES_REQUIRED = ["season", "home_club_id", "away_club_id", "fthg", "ftag", "date"]
_PANEL_REQUIRED = [
    "season", "club_id", "week1_shock", "week1_odds_source",
    "made_top4", "relegated", "final_points", "week1_opponent_id",
]


def _save_results(results: dict) -> None:
    """Write the (possibly partial) results dict to disk immediately."""
    def _clean(obj):
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_clean(v) for v in obj]
        if isinstance(obj, (np.floating, np.integer)):
            return obj.item()
        if isinstance(obj, float) and not math.isfinite(obj):
            return None
        return obj

    RESULTS_PATH.write_text(json.dumps(_clean(results), indent=2) + "\n")


def main() -> None:  # noqa: PLR0915 - one linear driver, intentionally verbose
    """Run the Wave 1 full-sample descriptive path end to end."""
    t_start = time.time()
    results: dict = {"stage": "wave1_full_sample_descriptive", "status": "running"}

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    matches = pd.read_parquet(DATA_DIR / "matches_all.parquet")
    check_df_schema(matches, _MATCHES_REQUIRED, "matches_all.parquet")
    panel = pd.read_parquet(DATA_DIR / "panel.parquet")
    check_df_schema(panel, _PANEL_REQUIRED, "panel.parquet")
    logger.info("loaded %d matches / %d panel rows", len(matches), len(panel))

    # Q1: 2007/08 is fetched solely to seed 2008/09's prior — it enters no fit.
    m0708 = load_matches("0708", "E0", use_cache=True)
    m0708.insert(0, "season", "0708")
    matches_ext = pd.concat([m0708, matches], ignore_index=True)
    logger.info("fetched 2007/08 seed season: %d matches", len(m0708))

    # ── 1. Full-sample hyperparameter fits (labelled descriptive) ────────────
    link = fit_link_params(matches)
    logger.info(
        "link: total_rate=%.4f rho=%.4f h=%.4f covid_h=%.4f",
        link.total_rate, link.rho, link.home_adv, link.covid_home_adv,
    )
    k_hat = fit_rational_k(list(_season_frames(matches).values()))
    logger.info("K_hat (raw Elo units): %s", k_hat)
    results["link"] = dataclasses.asdict(link)
    results["k_hat_raw_elo"] = k_hat
    _save_results(results)

    w, r_prom = fit_seed_params(matches, k_rational=k_hat, link=link)
    logger.info("seed params: w=%s R_prom=%s", w, r_prom)
    hp_partial = Hyperparams(w, r_prom, k_hat, float("nan"), link)
    lam = fit_lambda(matches, panel, hyperparams_partial=hp_partial)
    logger.info("lambda_hat: %s", lam)
    hyperparams = Hyperparams(w, r_prom, k_hat, lam, link)
    results["regress_weight_w"] = w
    results["promoted_baseline_r_prom"] = r_prom
    results["lambda_hat"] = lam
    _save_results(results)

    # ── 2. Priors for every season + the filled panel ────────────────────────
    priors = {}
    for season in SEASONS:
        src = matches_ext if season == "0809" else matches
        priors[season] = assign_tiers(build_prior_ratings(panel, src, season, hyperparams))
    panel_priors = fill_panel_priors(panel, priors)
    panel_priors.to_parquet(DATA_DIR / "panel_priors.parquet", index=False)
    logger.info("wrote data/panel_priors.parquet (%d rows)", len(panel_priors))

    # ── 3. Surprise frame + pooled regression (primary estimator) ────────────
    surprise = build_surprise_frame(matches, panel, priors, link, week=2)
    fit = pooled_surprise_regression(surprise)
    logger.info(
        "beta_market (constrained): %.5f (SE %.5f)", fit.beta_market, fit.se_market
    )
    logger.info(
        "unconstrained: beta_home=%.5f (SE %.5f) beta_away=%.5f (SE %.5f)",
        fit.beta_home, fit.se_home, fit.beta_away, fit.se_away,
    )
    results["surprise_frame"] = {
        "n_rows": int(len(surprise)),
        "n_week_mismatch": int(surprise["week_mismatch"].sum()),
        "mismatch_by_season": {
            s: int(n)
            for s, n in surprise.groupby("season")["week_mismatch"].sum().items()
            if n > 0
        },
    }
    results["beta_market"] = {
        "constrained": fit.beta_market,
        "constrained_se": fit.se_market,
        "unconstrained_home": fit.beta_home,
        "unconstrained_home_se": fit.se_home,
        "unconstrained_away": fit.beta_away,
        "unconstrained_away_se": fit.se_away,
        "symmetry_gap_home_plus_away": fit.beta_home + fit.beta_away,
        "n_matches": fit.n_matches,
        "n_seasons": fit.n_seasons,
    }
    _save_results(results)

    # ── 4. Per-season ridge secondary + pooled-vs-ridge divergence ───────────
    # Per season, the ridge fit's implied response is the through-origin slope
    # of its 20 market moves on the 20 Week-1 shocks — the same functional
    # form (move = c·shock) the pooled β̂ estimates. Under-identification
    # caveat: this slope is mechanically ∝ (1 − λ), stated wherever reported.
    shocks_by = panel.set_index(["season", "club_id"])["week1_shock"]
    ridge_slopes: dict[str, float] = {}
    for season in SEASONS:
        ridge = ridge_postweek1_fit(matches, season, priors[season], link, lam=lam)
        shock = np.array([shocks_by[(season, c)] for c in ridge["club_id"]])
        move = ridge["market_move"].to_numpy()
        ridge_slopes[season] = float((move @ shock) / (shock @ shock))
    slopes = np.array(list(ridge_slopes.values()))
    divergence = {
        "per_season_slopes": ridge_slopes,
        "mean": float(slopes.mean()),
        "median": float(np.median(slopes)),
        "sd": float(slopes.std(ddof=1)),
        "min": float(slopes.min()),
        "max": float(slopes.max()),
        "pooled_beta": fit.beta_market,
        "mean_abs_dev_from_pooled": float(np.abs(slopes - fit.beta_market).mean()),
        "note": "ridge slopes are mechanically proportional to (1 - lambda); "
                "under-identified on their own (see method spec)",
    }
    results["ridge_divergence"] = divergence
    logger.info(
        "ridge per-season slope: mean=%.5f median=%.5f sd=%.5f | mean |slope - pooled beta| = %.5f",
        divergence["mean"], divergence["median"], divergence["sd"],
        divergence["mean_abs_dev_from_pooled"],
    )
    _save_results(results)

    # ── 5. Commensuration (Q2) + the overreaction ratio ──────────────────────
    k_comm = commensurated_rational_slope(panel, priors, k_hat=k_hat, link=link)
    ratio = overreaction_ratio(fit.beta_market, k_comm, link=link)
    logger.info("commensurated rational slope: %.5f (supremacy per unit points-shock)", k_comm)
    logger.info("overreaction ratio: %.4f", ratio)
    results["k_hat_commensurated_slope"] = k_comm
    results["overreaction_ratio"] = ratio
    _save_results(results)

    # ── 6. Sanity gates ──────────────────────────────────────────────────────
    prior_final_r = float(
        np.corrcoef(panel_priors["prior_strength"], panel_priors["final_points"])[0, 1]
    )
    new_cols = ["prior_strength", "preseason_tier", "week1_opponent_tier"]
    nulls = {c: int(panel_priors[c].isna().sum()) for c in new_cols}
    gates = {
        "k_hat_positive_finite": bool(math.isfinite(k_hat) and k_hat > 0),
        "prior_vs_final_points_r": prior_final_r,
        "prior_vs_final_points_r_strong": bool(prior_final_r >= 0.6),
        "beta_market_positive": bool(fit.beta_market > 0),
        "panel_priors_rows": int(len(panel_priors)),
        "panel_priors_360_rows": bool(len(panel_priors) == 360),
        "panel_priors_new_col_nulls": nulls,
        "panel_priors_no_nulls": bool(sum(nulls.values()) == 0),
    }
    results["sanity_gates"] = gates
    results["status"] = "complete"
    results["runtime_seconds"] = round(time.time() - t_start, 1)
    _save_results(results)

    ok = lambda b: "PASS" if b else "FAIL"  # noqa: E731
    summary = "\n".join([
        "",
        "=" * 72,
        "WAVE 1 — FULL-SAMPLE DESCRIPTIVE SUMMARY (labelled: not LOSO)",
        "=" * 72,
        f"link:            mu (total_rate) = {link.total_rate:.4f}  rho = {link.rho:.4f}",
        f"                 h = {link.home_adv:.4f}  covid_h = {link.covid_home_adv:.4f}",
        f"seed:            w = {w}  R_prom = {r_prom}",
        f"shrinkage:       lambda_hat = {lam}",
        f"K_hat:           {k_hat} (raw Elo)  ->  {k_comm:.5f} (commensurated slope)",
        f"beta_market:     {fit.beta_market:.5f}  (clustered SE {fit.se_market:.5f}; "
        f"n = {fit.n_matches} matches, {fit.n_seasons} seasons)",
        f"  symmetry chk:  beta_home = {fit.beta_home:.5f}, beta_away = {fit.beta_away:.5f} "
        f"(home + away = {fit.beta_home + fit.beta_away:+.5f})",
        f"overreaction:    beta_market / K_commensurated = {ratio:.4f}",
        f"ridge secondary: per-season slope mean {divergence['mean']:.5f} "
        f"(sd {divergence['sd']:.5f}), mean |dev from pooled| "
        f"{divergence['mean_abs_dev_from_pooled']:.5f}",
        "-" * 72,
        f"[{ok(gates['k_hat_positive_finite'])}] K_hat positive and finite: {k_hat}",
        f"[{ok(gates['prior_vs_final_points_r_strong'])}] "
        f"prior_strength vs final_points pooled Pearson r = {prior_final_r:.4f} (need >= 0.6)",
        f"[{ok(gates['beta_market_positive'])}] beta_market positive: {fit.beta_market:.5f}",
        f"[{ok(gates['panel_priors_360_rows'] and gates['panel_priors_no_nulls'])}] "
        f"panel_priors: {len(panel_priors)} rows, nulls {nulls}",
        "-" * 72,
        f"artifacts: data/panel_priors.parquet, data/wave1_results.json "
        f"({results['runtime_seconds']}s)",
    ])
    logger.info("%s", summary)


if __name__ == "__main__":
    main()
