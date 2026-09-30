"""Score the horse race: Brier / log-loss / RPS, paired by season.

Estimand 1 (the headline): P(top-4) and P(relegation) accuracy at prior vs
rational posterior vs market posterior, evaluated leave-one-season-out.
Scored as paired per-season differences with a season-block bootstrap and
sign test — never pooled team-seasons treated as independent, because each
season fixes exactly 4 top-4 and 3 relegation slots. RPS over finish
positions is the quota-respecting robustness check. Reliability curves are
read *before* the horse race (Brier rewards miscalibrated sharpness); the
two pre-registered primaries (Brier difference, market posterior vs prior,
top-4 and relegation) are Holm-corrected.
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np
import pandas as pd
from footy_stats.stats.calibration import brier_score, log_loss, reliability_curve, rps
from scipy.stats import binomtest

#: Metric columns produced by :func:`score_checkpoint`, in reporting order.
METRICS: tuple[str, ...] = ("brier_top4", "brier_releg", "logloss_top4", "logloss_releg", "rps")

#: (target label, probability column, outcome column) pairs for the two
#: binary horse-race targets.
_TARGETS: tuple[tuple[str, str, str], ...] = (
    ("top4", "p_top4", "made_top4"),
    ("releg", "p_relegation", "relegated"),
)


def score_checkpoint(sim: pd.DataFrame, outcomes: pd.DataFrame) -> dict[str, float]:
    """Score one checkpoint's simulated season against actual outcomes.

    Wraps ``footy_stats.stats.calibration``: Brier and log-loss on
    ``p_top4`` vs ``made_top4`` and ``p_relegation`` vs ``relegated``, plus
    RPS of the ``p_pos_*`` matrix against ``final_position``.

    Args:
        sim: Output of ``simulate_season`` for one (season, checkpoint) —
            indexed by club with ``p_top4``, ``p_relegation``, ``p_pos_*``.
        outcomes: That season's panel rows (``club_id``, ``made_top4``,
            ``relegated``, ``final_position``).

    Returns:
        ``{"brier_top4", "brier_releg", "logloss_top4", "logloss_releg",
        "rps"}`` for this season-checkpoint.
    """
    merged = (
        sim.reset_index()
        .rename(columns={"index": "club_id"})
        .merge(
            outcomes[["club_id", "made_top4", "relegated", "final_position"]],
            on="club_id",
            validate="1:1",
        )
    )
    pos_cols = sorted(
        (c for c in sim.columns if c.startswith("p_pos_")),
        key=lambda c: int(c.rsplit("_", 1)[1]),
    )
    return {
        "brier_top4": brier_score(merged["p_top4"], merged["made_top4"].astype(int)),
        "brier_releg": brier_score(merged["p_relegation"], merged["relegated"].astype(int)),
        "logloss_top4": log_loss(merged["p_top4"], merged["made_top4"].astype(int)),
        "logloss_releg": log_loss(merged["p_relegation"], merged["relegated"].astype(int)),
        "rps": rps(merged[pos_cols].to_numpy(), merged["final_position"].to_numpy()),
    }


def collect_scores(
    sims: Mapping[tuple[str, str], pd.DataFrame],
    panel: pd.DataFrame,
) -> pd.DataFrame:
    """Assemble per-season, per-checkpoint scores into one tidy frame.

    Args:
        sims: (season, checkpoint) → ``simulate_season`` output, as produced
            by the LOSO driver (``loso.run_loso``).
        panel: The Stage 1 team-season panel (supplies outcomes).

    Returns:
        One row per (season, checkpoint) with the metric columns of
        :func:`score_checkpoint`.
    """
    rows: list[dict] = []
    for (season, checkpoint), sim in sims.items():
        outcomes = panel.loc[panel["season"] == season]
        rows.append(
            {"season": season, "checkpoint": checkpoint, **score_checkpoint(sim, outcomes)}
        )
    return pd.DataFrame.from_records(rows).sort_values(["season", "checkpoint"]).reset_index(
        drop=True
    )


def paired_differences(scores: pd.DataFrame, *, baseline: str = "prior") -> pd.DataFrame:
    """Compute per-season score differences of each checkpoint vs a baseline.

    The overreaction read: market posterior no better (or worse) than the
    prior. Differences are paired within season — the unit of independence.

    Args:
        scores: Output of :func:`collect_scores`.
        baseline: Checkpoint subtracted from the others (default the prior).

    Returns:
        One row per (season, checkpoint ≠ baseline) with differenced metric
        columns (checkpoint − baseline; negative favors the checkpoint).
    """
    metrics = list(METRICS)
    base = scores.loc[scores["checkpoint"] == baseline].set_index("season")[metrics]
    rows: list[dict] = []
    for checkpoint in scores["checkpoint"].unique():
        if checkpoint == baseline:
            continue
        sub = scores.loc[scores["checkpoint"] == checkpoint].set_index("season")[metrics]
        diff = sub - base.loc[sub.index]
        for season, row in diff.iterrows():
            rows.append({"season": season, "checkpoint": checkpoint, **row.to_dict()})
    return pd.DataFrame.from_records(rows)


def season_block_bootstrap(
    diffs: pd.DataFrame,
    *,
    n_boot: int = 10_000,
    seed: int | None = None,
) -> pd.DataFrame:
    """Bootstrap CIs for mean paired differences, resampling whole seasons.

    Seasons are the exchangeable blocks; team-seasons within a season are
    never resampled independently (fixed quotas). Also the CI machinery for
    the overreaction ratio and the decay curve's β_k.

    Args:
        diffs: Output of :func:`paired_differences` (or any frame with a
            ``season`` column and numeric metric columns).
        n_boot: Bootstrap replicates.
        seed: RNG seed for reproducibility.

    Returns:
        One row per (checkpoint, metric): mean difference, 2.5 / 97.5
        percentile bounds, bootstrap SE.
    """
    rng = np.random.default_rng(seed)
    metrics = [c for c in METRICS if c in diffs.columns]
    rows: list[dict] = []
    for checkpoint in diffs["checkpoint"].unique():
        sub = diffs.loc[diffs["checkpoint"] == checkpoint]
        assert sub["season"].is_unique, "season_block_bootstrap requires one row per season"
        values = sub[metrics].to_numpy(dtype=float)  # (n_seasons, n_metrics)
        n_seasons = values.shape[0]
        idx = rng.integers(0, n_seasons, size=(n_boot, n_seasons))
        boot_means = values[idx].mean(axis=1)  # (n_boot, n_metrics)
        for j, metric in enumerate(metrics):
            rows.append(
                {
                    "checkpoint": checkpoint,
                    "metric": metric,
                    "mean_diff": float(values[:, j].mean()),
                    "ci_low": float(np.percentile(boot_means[:, j], 2.5)),
                    "ci_high": float(np.percentile(boot_means[:, j], 97.5)),
                    "se": float(boot_means[:, j].std(ddof=1)),
                }
            )
    return pd.DataFrame.from_records(rows)


def sign_test(diffs: pd.Series) -> float:
    """Exact two-sided sign test on per-season paired differences.

    The distribution-free companion to the bootstrap: counts seasons where
    the checkpoint beats the baseline, against a fair coin.

    Args:
        diffs: One paired difference per season for a single (checkpoint,
            metric) combination.

    Returns:
        The two-sided p-value.
    """
    clean = diffs.dropna()
    clean = clean[clean != 0]  # exact sign test discards ties
    n_wins = int((clean < 0).sum())  # negative = checkpoint beats the baseline
    return float(binomtest(n_wins, n=len(clean), p=0.5, alternative="two-sided").pvalue)


def holm_correct(pvals: Mapping[str, float]) -> dict[str, float]:
    """Holm-correct the two pre-registered primary comparisons.

    Primaries: Brier difference, market posterior vs prior, for top-4 and for
    relegation (method spec, "Multiple comparisons"). Everything else is
    labelled secondary or descriptive and stays uncorrected.

    Args:
        pvals: Label → raw p-value for the primary family.

    Returns:
        Label → Holm-adjusted p-value.
    """
    m = len(pvals)
    ordered = sorted(pvals.items(), key=lambda kv: kv[1])
    adjusted: dict[str, float] = {}
    running_max = 0.0
    for k, (label, raw) in enumerate(ordered):
        adj = min(1.0, raw * (m - k))
        running_max = max(running_max, adj)
        adjusted[label] = running_max
    return adjusted


def reliability_by_checkpoint(
    probs: pd.DataFrame,
    *,
    bins: int = 5,
    n_boot: int = 2_000,
    seed: int | None = None,
) -> pd.DataFrame:
    """Build reliability curves with season-block bootstrap bands.

    Quintile bins over pooled LOSO output (~300+ team-seasons; ~60 top-4 and
    ~45 relegation positives), per checkpoint and target, via
    ``footy_stats.stats.calibration.reliability_curve``. Read before the
    horse race; miscalibration is reported *with* the horse race, never
    instead of it.

    Args:
        probs: Pooled LOSO probabilities — one row per (season, club,
            checkpoint) with ``p_top4``, ``p_relegation`` and the outcome
            columns.
        bins: Probability bins (quintiles per spec; finer is out of reach at
            this n).
        n_boot: Season-block bootstrap replicates for the bands.
        seed: RNG seed.

    Returns:
        One row per (checkpoint, target, bin): mean predicted, observed rate,
        band bounds, bin count.
    """
    rng = np.random.default_rng(seed)
    rows: list[dict] = []
    for checkpoint in probs["checkpoint"].unique():
        sub = probs.loc[probs["checkpoint"] == checkpoint]
        seasons = sub["season"].unique()
        by_season = {s: sub.loc[sub["season"] == s] for s in seasons}
        for target, p_col, o_col in _TARGETS:
            base = reliability_curve(sub[p_col], sub[o_col].astype(int), bins=bins)
            boot_freq = np.full((n_boot, len(base)), np.nan)
            for b in range(n_boot):
                pick = rng.choice(seasons, size=len(seasons), replace=True)
                resample = pd.concat([by_season[s] for s in pick], ignore_index=True)
                curve = reliability_curve(resample[p_col], resample[o_col].astype(int), bins=bins)
                k = min(len(curve), len(base))
                boot_freq[b, :k] = curve["observed_freq"].to_numpy()[:k]
            ci_low = np.nanpercentile(boot_freq, 2.5, axis=0)
            ci_high = np.nanpercentile(boot_freq, 97.5, axis=0)
            for i, row in base.iterrows():
                rows.append(
                    {
                        "checkpoint": checkpoint,
                        "target": target,
                        "bin_idx": int(i),
                        "mean_predicted": float(row["mean_predicted"]),
                        "observed_freq": float(row["observed_freq"]),
                        "count": int(row["count"]),
                        "ci_low": float(ci_low[i]),
                        "ci_high": float(ci_high[i]),
                    }
                )
    return pd.DataFrame.from_records(rows)
