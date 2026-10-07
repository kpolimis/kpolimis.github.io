"""Wave 3 driver: the decay curve for the Week-1 overreaction study.

Runs estimand 3 (the reversal test): re-fits the pooled surprise regression
against Week-k odds for k = 2…6, tracing how much of the Week-1-induced move
survives as the season's evidence accumulates. β_k shrinking toward 0 is the
market unwinding its own move — the classic reversal signature, and fully
transport-free.

Full-sample DESCRIPTIVE, not LOSO: priors and link are loaded from the Wave 1
artifacts (``data/panel_priors.parquet``, ``data/wave1_results.json``) —
nothing is re-fitted here. CIs are season-block bootstrap (10,000 replicates,
seed 42). See STAGE2_SCOPE.md, "Two roles for β̂".

Run from the post directory:

    python3 run_wave3.py
"""

from __future__ import annotations

import json
import logging
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
from analysis.decay import fit_decay_curve
from analysis.params import SEASONS, LinkParams, check_df_schema
from footy_stats.cache import freeze

logger = logging.getLogger(__name__)

POST_DIR = Path(__file__).resolve().parent
DATA_DIR = POST_DIR / "data"
RESULTS_PATH = DATA_DIR / "wave3_results.json"

#: β_2 must reproduce Wave 1's headline β̂_market within this tolerance.
_CONSISTENCY_TOL = 0.001

_MATCHES_REQUIRED = ["season", "home_club_id", "away_club_id", "fthg", "ftag", "date"]
_PANEL_PRIORS_REQUIRED = [
    "season", "club_id", "prior_strength", "preseason_tier",
    "week1_opponent_tier", "week1_shock", "final_points",
]
_WAVE1_REQUIRED_KEYS = {"link", "beta_market"}


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


def _log_headline(decay: pd.DataFrame, k2_beta: float, wave1_beta: float, runtime: float) -> None:
    """Log the ASCII headline table via logger.info."""
    diff = abs(k2_beta - wave1_beta)
    verdict = "PASS" if diff < _CONSISTENCY_TOL else "FAIL"
    lines = [
        "",
        "=" * 64,
        "WAVE 3 — DECAY CURVE (estimand 3: does the market unwind?)",
        "=" * 64,
        "full-sample descriptive (Wave 1 priors + link; NOT LOSO)",
        f"{'week':>4}   {'beta_k':>6}   {'se':>5}  {'95% CI':<19} "
        f"{'n_matches':>9}  {'n_seasons':>9}  {'%closing':>8}",
    ]
    for row in decay.itertuples(index=False):
        ci = f"[{row.ci_lo:.4f}, {row.ci_hi:.4f}]"
        lines.append(
            f"{row.week:>4}   {row.beta_market:.4f}  {row.se_market:.3f}  {ci:<19} "
            f"{row.n_matches:>9}  {row.n_seasons:>9}  {row.share_closing:>7.0%}"
        )
    lines.extend([
        "-" * 64,
        f"consistency check: wave3 k=2 beta vs wave1 beta_market "
        f"(should match within {_CONSISTENCY_TOL}):",
        f"  wave3 k=2: {k2_beta:.5f}  wave1: {wave1_beta:.5f}  diff: {diff:.5f}  [{verdict}]",
        "-" * 64,
        f"artifacts: data/decay_curve.parquet, data/wave3_results.json ({runtime:.1f}s)",
    ])
    logger.info("%s", "\n".join(lines))


def main() -> None:
    """Run the Wave 3 decay curve end to end."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    t_start = time.time()
    results: dict = {"stage": "wave3_decay_curve_descriptive", "status": "running"}

    matches = pd.read_parquet(DATA_DIR / "matches_all.parquet")
    check_df_schema(matches, _MATCHES_REQUIRED, "matches_all.parquet")
    panel_priors = pd.read_parquet(DATA_DIR / "panel_priors.parquet")
    check_df_schema(panel_priors, _PANEL_PRIORS_REQUIRED, "panel_priors.parquet")
    logger.info("loaded %d matches / %d panel_priors rows", len(matches), len(panel_priors))

    # Wave 1 artifacts only — nothing is re-fitted here.
    w1 = json.loads((DATA_DIR / "wave1_results.json").read_text())
    missing_keys = _WAVE1_REQUIRED_KEYS - w1.keys()
    if missing_keys:
        raise ValueError(f"wave1_results.json: missing required keys {sorted(missing_keys)}")
    link = LinkParams(**w1["link"])
    logger.info(
        "link (from wave1): mu=%.4f rho=%.4f h=%.4f covid_h=%.4f",
        link.total_rate, link.rho, link.home_adv, link.covid_home_adv,
    )
    priors_by_season = {
        season: panel_priors.loc[
            panel_priors["season"] == season, ["club_id", "prior_strength"]
        ].copy()
        for season in SEASONS
    }

    decay = fit_decay_curve(matches, panel_priors, priors_by_season, link)
    freeze(decay, DATA_DIR, "decay_curve")
    logger.info("wrote data/decay_curve.parquet (%d rows)", len(decay))

    wave1_beta = float(w1["beta_market"]["constrained"])
    k2_beta = float(decay.loc[decay["week"] == 2, "beta_market"].iloc[0])
    consistency_ok = bool(abs(k2_beta - wave1_beta) < _CONSISTENCY_TOL)

    results.update(
        {
            "decay_curve": decay.to_dict(orient="records"),
            "consistency_check": {
                "wave3_k2_beta": k2_beta,
                "wave1_beta_market": wave1_beta,
                "abs_diff": abs(k2_beta - wave1_beta),
                "tolerance": _CONSISTENCY_TOL,
                "pass": consistency_ok,
            },
            "sanity_gates": {
                "k2_matches_wave1_beta": consistency_ok,
                "n_weeks": int(len(decay)),
                "all_weeks_present": bool(sorted(decay["week"]) == [2, 3, 4, 5, 6]),
            },
            "note": "full-sample descriptive (Wave 1 priors + link; not LOSO); "
                    "season-block bootstrap CIs, n_boot=10000, seed=42",
            "status": "complete",
            "runtime_seconds": round(time.time() - t_start, 1),
        }
    )
    _save_results(results)
    _log_headline(decay, k2_beta, wave1_beta, results["runtime_seconds"])


if __name__ == "__main__":
    main()
