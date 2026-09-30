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
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
from analysis.decay import fit_decay_curve
from analysis.params import SEASONS, LinkParams
from footy_stats.cache import freeze

POST_DIR = Path(__file__).resolve().parent
DATA_DIR = POST_DIR / "data"
RESULTS_PATH = DATA_DIR / "wave3_results.json"

#: β_2 must reproduce Wave 1's headline β̂_market within this tolerance.
_CONSISTENCY_TOL = 0.001


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


def _print_headline(decay: pd.DataFrame, k2_beta: float, wave1_beta: float, runtime: float) -> None:
    """Print the ASCII headline table (models run_wave1's summary block)."""
    print("\n" + "=" * 64)
    print("WAVE 3 — DECAY CURVE (estimand 3: does the market unwind?)")
    print("=" * 64)
    print("full-sample descriptive (Wave 1 priors + link; NOT LOSO)")
    print(f"{'week':>4}   {'beta_k':>6}   {'se':>5}  {'95% CI':<19} "
          f"{'n_matches':>9}  {'n_seasons':>9}  {'%closing':>8}")
    for row in decay.itertuples(index=False):
        ci = f"[{row.ci_lo:.4f}, {row.ci_hi:.4f}]"
        print(f"{row.week:>4}   {row.beta_market:.4f}  {row.se_market:.3f}  {ci:<19} "
              f"{row.n_matches:>9}  {row.n_seasons:>9}  {row.share_closing:>7.0%}")
    print("-" * 64)
    diff = abs(k2_beta - wave1_beta)
    verdict = "PASS" if diff < _CONSISTENCY_TOL else "FAIL"
    print("consistency check: wave3 k=2 beta vs wave1 beta_market "
          f"(should match within {_CONSISTENCY_TOL}):")
    print(f"  wave3 k=2: {k2_beta:.5f}  wave1: {wave1_beta:.5f}  "
          f"diff: {diff:.5f}  [{verdict}]")
    print("-" * 64)
    print(f"artifacts: data/decay_curve.parquet, data/wave3_results.json ({runtime:.1f}s)")


def main() -> None:
    """Run the Wave 3 decay curve end to end."""
    t_start = time.time()
    results: dict = {"stage": "wave3_decay_curve_descriptive", "status": "running"}

    matches = pd.read_parquet(DATA_DIR / "matches_all.parquet")
    panel_priors = pd.read_parquet(DATA_DIR / "panel_priors.parquet")
    print(f"loaded {len(matches)} matches / {len(panel_priors)} panel_priors rows")

    # Wave 1 artifacts only — nothing is re-fitted here.
    w1 = json.loads((DATA_DIR / "wave1_results.json").read_text())
    link = LinkParams(**w1["link"])
    print(f"link (from wave1): mu={link.total_rate:.4f} rho={link.rho:.4f} "
          f"h={link.home_adv:.4f} covid_h={link.covid_home_adv:.4f}")
    priors_by_season = {
        season: panel_priors.loc[
            panel_priors["season"] == season, ["club_id", "prior_strength"]
        ].copy()
        for season in SEASONS
    }

    decay = fit_decay_curve(matches, panel_priors, priors_by_season, link)
    freeze(decay, DATA_DIR, "decay_curve")
    print(f"wrote data/decay_curve.parquet ({len(decay)} rows)")

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
    _print_headline(decay, k2_beta, wave1_beta, results["runtime_seconds"])


if __name__ == "__main__":
    main()
