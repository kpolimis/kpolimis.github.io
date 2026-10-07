"""Wave 2 driver: nested LOSO horse-race for the Week-1 overreaction study.

Runs the STAGE2_SCOPE nested-LOSO path: one fold per season, every fitted
scalar re-estimated on the 17 training seasons, three checkpoint transports
simulated over all 380 fixtures (Q5), scored via ``horse_race`` with a
season-block bootstrap, sign tests, and Holm correction of the two
pre-registered primaries. Artifacts are frozen into ``data/`` and the
headline scalars land in ``data/wave2_results.json``.

Run from the post directory:

    python3 run_wave2.py
"""

from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
from analysis.horse_race import (
    holm_correct,
    paired_differences,
    reliability_by_checkpoint,
    season_block_bootstrap,
    sign_test,
)
from analysis.loso import freeze_outputs, run_loso
from analysis.params import CHECKPOINTS, SEASONS, check_df_schema
from footy_stats.cache import freeze
from footy_stats.sources.football_data import load_matches

logger = logging.getLogger(__name__)

POST_DIR = Path(__file__).resolve().parent
DATA_DIR = POST_DIR / "data"
RESULTS_PATH = DATA_DIR / "wave2_results.json"

#: The two pre-registered primaries (Brier, market posterior vs prior).
_PRIMARIES = {"brier_top4_market_vs_prior": "brier_top4", "brier_releg_market_vs_prior": "brier_releg"}

_MATCHES_REQUIRED = ["season", "home_club_id", "away_club_id", "fthg", "ftag", "date"]
_PANEL_REQUIRED = [
    "season", "club_id", "week1_shock", "week1_odds_source",
    "made_top4", "relegated", "final_points", "week1_opponent_id",
]
_WAVE1_REQUIRED_KEYS = {"link", "beta_market", "k_hat_commensurated_slope", "overreaction_ratio"}


def _save_results(results: dict) -> None:
    """Write the (possibly partial) results dict to disk immediately."""

    def _clean(obj):
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_clean(v) for v in obj]
        if isinstance(obj, (np.floating, np.integer)):
            return obj.item()
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, float) and not math.isfinite(obj):
            return None
        return obj

    RESULTS_PATH.write_text(json.dumps(_clean(results), indent=2) + "\n")


def _log_headline(
    result,
    mean_scores: pd.DataFrame,
    boot: pd.DataFrame,
    pvals: dict[str, float],
    holm: dict[str, float],
    gates: dict,
    wave1: dict,
    runtime: float,
) -> None:
    """Log the ASCII headline summary block via logger.info."""
    ok = lambda b: "PASS" if b else "FAIL"  # noqa: E731
    mkt = boot.loc[boot["checkpoint"] == "market"].set_index("metric")
    rat = boot.loc[boot["checkpoint"] == "rational"].set_index("metric")
    top4 = mkt.loc["brier_top4"]
    releg = mkt.loc["brier_releg"]

    lines = [
        "",
        "=" * 72,
        "WAVE 2 — NESTED LOSO HORSE RACE (the headline evidence)",
        "=" * 72,
        f"folds: {len(result.fold_fits)} seasons, all scalars re-fitted per fold",
        "",
        "per-checkpoint LOSO means (18 seasons):",
        f"{'checkpoint':<10} {'brier_top4':>11} {'brier_releg':>12} "
        f"{'logloss_top4':>13} {'logloss_releg':>14} {'rps':>8}",
    ]
    for ckpt in CHECKPOINTS:
        row = mean_scores.loc[ckpt]
        lines.append(
            f"{ckpt:<10} {row['brier_top4']:>11.5f} {row['brier_releg']:>12.5f} "
            f"{row['logloss_top4']:>13.5f} {row['logloss_releg']:>14.5f} {row['rps']:>8.5f}"
        )
    lines.append("\nmarket vs prior (negative = market better), season-block bootstrap:")
    for metric in ("brier_top4", "brier_releg", "logloss_top4", "logloss_releg", "rps"):
        row = mkt.loc[metric]
        lines.append(
            f"  {metric:<14} mean diff {row['mean_diff']:+.5f}  "
            f"95% CI [{row['ci_low']:+.5f}, {row['ci_high']:+.5f}]  se {row['se']:.5f}"
        )
    lines.append("\nrational vs prior (negative = rational better):")
    for metric in ("brier_top4", "brier_releg"):
        row = rat.loc[metric]
        lines.append(
            f"  {metric:<14} mean diff {row['mean_diff']:+.5f}  "
            f"95% CI [{row['ci_low']:+.5f}, {row['ci_high']:+.5f}]"
        )
    lines.append("\npre-registered primaries (sign test, Holm-corrected):")
    for label in _PRIMARIES:
        lines.append(
            f"  {label:<30} raw p = {pvals[label]:.4f}  holm p = {holm[label]:.4f}"
        )
    lines.append(
        f"\noverreaction ratio (Wave 1, full-sample descriptive): "
        f"{wave1['overreaction_ratio']:.4f}"
    )
    lines.append("-" * 72)
    lines.append(f"[{ok(gates['n_folds_18'])}] n_folds == 18: {gates['n_folds']}")
    lines.append(
        f"[{ok(gates['scores_shape_54x7'])}] loso_scores shape == (54, 7): "
        f"{gates['scores_shape']} ({gates['n_score_checkpoints']} checkpoints, "
        f"{gates['n_score_seasons']} seasons)"
    )
    lines.append(f"[{ok(gates['sims_rows_1080'])}] loso_sims rows == 1080: {gates['sims_rows']}")
    lines.append(
        f"[{ok(gates['brier_in_unit_interval'])}] all Brier scores in [0, 1] "
        f"(max {gates['max_brier']:.5f})"
    )
    lines.append(
        f"[{ok(gates['logloss_in_unit_interval'])}] all log-loss scores in [0, 1] "
        f"(max {gates['max_logloss']:.5f})"
    )
    for name, row, label in (("top4", top4, "brier_top4_market_vs_prior"),
                             ("releg", releg, "brier_releg_market_vs_prior")):
        verdict = "market better" if row["mean_diff"] < 0 else "prior better"
        lines.append(
            f"[INFO] market vs prior Brier {name}: {row['mean_diff']:+.5f} ({verdict}); "
            f"CI [{row['ci_low']:+.5f}, {row['ci_high']:+.5f}]; "
            f"sign test holm p = {holm[label]:.4f}"
        )
    lines.append("-" * 72)
    lines.append(
        f"artifacts: data/loso_sims.parquet, data/loso_scores.parquet, "
        f"data/loso_fold_params.parquet, data/loso_diffs.parquet, "
        f"data/loso_boot.parquet, data/loso_reliability.parquet, "
        f"data/wave2_results.json ({runtime:.1f}s)"
    )
    logger.info("%s", "\n".join(lines))


def main() -> None:
    """Run the Wave 2 nested-LOSO horse race end to end."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    t_start = time.time()
    results: dict = {"stage": "wave2_nested_loso_horse_race", "status": "running"}

    matches = pd.read_parquet(DATA_DIR / "matches_all.parquet")
    check_df_schema(matches, _MATCHES_REQUIRED, "matches_all.parquet")
    panel = pd.read_parquet(DATA_DIR / "panel.parquet")
    check_df_schema(panel, _PANEL_REQUIRED, "panel.parquet")
    logger.info("loaded %d matches / %d panel rows", len(matches), len(panel))

    # Q1: 2007/08 is fetched solely to seed 2008/09's prior — it enters no fit
    # (train_matches is always filtered to a subset of SEASONS).
    m0708 = load_matches("0708", "E0", use_cache=True)
    m0708.insert(0, "season", "0708")
    matches_ext = pd.concat([m0708, matches], ignore_index=True)
    logger.info("fetched 2007/08 seed season: %d matches", len(m0708))

    result = run_loso(matches_ext, panel, n_sims=10_000, seed=42, verbose=True)
    results["n_folds"] = len(result.fold_fits)
    _save_results(results)

    diffs = paired_differences(result.scores)
    boot = season_block_bootstrap(diffs, n_boot=10_000, seed=42)
    market_diffs = diffs.loc[diffs["checkpoint"] == "market"]
    pvals = {
        label: sign_test(market_diffs.set_index("season")[metric])
        for label, metric in _PRIMARIES.items()
    }
    holm = holm_correct(pvals)

    probs = result.sims[["season", "checkpoint", "club_id", "p_top4", "p_relegation"]].merge(
        panel[["season", "club_id", "made_top4", "relegated"]],
        on=["season", "club_id"],
        validate="m:1",
    )
    reliability = reliability_by_checkpoint(probs, bins=5, n_boot=2_000, seed=42)

    freeze_outputs(result, DATA_DIR)
    freeze(diffs, DATA_DIR, "loso_diffs")
    freeze(boot, DATA_DIR, "loso_boot")
    freeze(reliability, DATA_DIR, "loso_reliability")

    wave1 = json.loads((DATA_DIR / "wave1_results.json").read_text())
    missing_keys = _WAVE1_REQUIRED_KEYS - wave1.keys()
    if missing_keys:
        raise ValueError(f"wave1_results.json: missing required keys {sorted(missing_keys)}")
    mean_scores = result.scores.groupby("checkpoint", observed=True)[
        ["brier_top4", "brier_releg", "logloss_top4", "logloss_releg", "rps"]
    ].mean()

    brier_vals = result.scores[["brier_top4", "brier_releg"]].to_numpy()
    logloss_vals = result.scores[["logloss_top4", "logloss_releg"]].to_numpy()
    gates = {
        "n_folds": len(result.fold_fits),
        "n_folds_18": bool(len(result.fold_fits) == 18),
        "scores_shape": list(result.scores.shape),
        "scores_shape_54x7": bool(result.scores.shape == (54, 7)),
        "n_score_checkpoints": int(result.scores["checkpoint"].nunique()),
        "n_score_seasons": int(result.scores["season"].nunique()),
        "sims_rows": int(len(result.sims)),
        "sims_rows_1080": bool(len(result.sims) == 18 * 3 * 20),
        "max_brier": float(brier_vals.max()),
        "brier_in_unit_interval": bool((brier_vals >= 0).all() and (brier_vals <= 1).all()),
        "max_logloss": float(logloss_vals.max()),
        "logloss_in_unit_interval": bool(
            (logloss_vals >= 0).all() and (logloss_vals <= 1).all()
        ),
    }

    results.update(
        {
            "mean_scores_by_checkpoint": {
                ckpt: {k: float(v) for k, v in mean_scores.loc[ckpt].items()}
                for ckpt in CHECKPOINTS
            },
            "bootstrap_vs_prior": boot.to_dict(orient="records"),
            "sign_test_raw_p": pvals,
            "sign_test_holm_p": holm,
            "fold_params": {
                fold.holdout_season: {
                    "k_rational": fold.hyperparams.k_rational,
                    "regress_weight": fold.hyperparams.regress_weight,
                    "promoted_baseline": fold.hyperparams.promoted_baseline,
                    "lam": fold.hyperparams.lam,
                    "beta_market": fold.beta_market,
                    "k_commensurated": fold.k_commensurated,
                }
                for fold in result.fold_fits
            },
            "overreaction_ratio_wave1": wave1["overreaction_ratio"],
            "sanity_gates": gates,
            "n_seasons_expected": len(SEASONS),
            "status": "complete",
            "runtime_seconds": round(time.time() - t_start, 1),
        }
    )
    _save_results(results)
    _log_headline(
        result, mean_scores, boot, pvals, holm, gates, wave1, results["runtime_seconds"]
    )


if __name__ == "__main__":
    main()
