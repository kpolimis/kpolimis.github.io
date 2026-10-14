"""analyze_durability.py — E1 (career durability) and E3 (shot selection) analysis.

Implements the primary estimands from method-spec.md §3 for any configured cohort.
Run after fetch_bref_data.py has populated data/game_logs.parquet.

Usage:
    conda run -n blog python analyze_durability.py --cohort pg
    conda run -n blog python analyze_durability.py --cohort pf
    conda run -n blog python analyze_durability.py --cohort population
"""

import argparse
import logging
import pathlib

import matplotlib
import numpy as np
import pandas as pd
from scipy import stats

matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA_DIR = pathlib.Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# Season game counts; shortened seasons explicit
SEASON_GAMES: dict[int, int] = {y: 82 for y in range(1982, 2025)}
SEASON_GAMES.update({1999: 50, 2012: 66, 2020: 65, 2021: 72})

# Cohort membership sets (player_id)
PG_IDS = {
    "stockjo01",
    "thomais01",
    "johnske02",
    "hardati01",
    "paytoga01",
    "jacksma01",
    "portete01",
    "stricro02",
    "boguemu01",
    "douglsh01",
    "kiddja01",
    "harpede01",
    "blaylmo01",
    "anderke01",
    "nashst01",
}
PF_IDS = {
    "diawbo01",
    "nowitdi01",
    "boozeca01",
    "jamisan01",
    "mariosh01",
    "lewisra02",
}


def _parse_mp(mp_str: str) -> float | None:
    """'34:21' → 34.35; returns None for non-playing rows."""
    if not isinstance(mp_str, str) or ":" not in mp_str:
        return None
    try:
        m, s = mp_str.split(":")
        return int(m) + int(s) / 60
    except ValueError:
        return None


def load_cohort(cohort: str) -> tuple[pd.DataFrame, str | None, str | None]:
    """Load and filter game logs for the given cohort.

    Returns (df, treated_player_id, treated_player_name).
    For population cohort, treated_id/name are None.
    """
    if cohort not in ("pg", "pf", "population"):
        raise ValueError(f"Unknown cohort: {cohort!r}. Use pg, pf, or population.")

    parquet = DATA_DIR / "game_logs.parquet"
    if not parquet.exists():
        raise FileNotFoundError("data/game_logs.parquet not found — run fetch_bref_data.py first.")

    df = pd.read_parquet(parquet)
    df["mp_float"] = df["MP"].apply(_parse_mp)
    df = df[df["mp_float"].notna()].copy()  # active games only

    if cohort == "pg":
        df = df[df["player_id"].isin(PG_IDS)].copy()
        treated_id, treated_name = "stockjo01", "John Stockton"
    elif cohort == "pf":
        df = df[df["player_id"].isin(PF_IDS)].copy()
        treated_id, treated_name = "diawbo01", "Boris Diaw"
    else:
        treated_id, treated_name = None, None

    n_players = df["player_id"].nunique()
    logger.info("Cohort=%s: %s rows, %d players", cohort, f"{len(df):,}", n_players)
    if n_players < 2:
        logger.warning(
            "Only %d player(s) in cohort — analysis requires ≥2 players for comparison. "
            "Fetch remaining cohort players with fetch_bref_data.py first.",
            n_players,
        )
    return df, treated_id, treated_name


def compute_e1(
    df: pd.DataFrame,
    treated_id: str | None,
) -> tuple[pd.DataFrame, float | None]:
    """Compute games-missed-per-82 for each player.

    Returns (summary_df, treated_gmiss_per_82).
    summary_df columns: player_id, player_name, career_seasons, total_season_games,
                        active_games, games_missed, games_missed_per_82.
    """
    rows = []
    for pid, pdata in df.groupby("player_id"):
        name = pdata["player_name"].iloc[0] if "player_name" in pdata.columns else pid
        per_season = pdata.groupby("season").agg(active_games=("Date", "count")).reset_index()
        per_season["season_games"] = per_season["season"].map(SEASON_GAMES).fillna(82)
        per_season["missed"] = (per_season["season_games"] - per_season["active_games"]).clip(
            lower=0
        )
        total_sg = per_season["season_games"].sum()
        total_active = per_season["active_games"].sum()
        total_missed = per_season["missed"].sum()
        # games_missed_per_82 = missed rate normalized to an 82-game season
        gmiss82 = (total_missed / total_sg * 82) if total_sg > 0 else float("nan")
        rows.append(
            {
                "player_id": pid,
                "player_name": name,
                "career_seasons": len(per_season),
                "total_season_games": int(total_sg),
                "active_games": int(total_active),
                "games_missed": int(total_missed),
                "games_missed_per_82": gmiss82,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "player_id",
                "player_name",
                "career_seasons",
                "total_season_games",
                "active_games",
                "games_missed",
                "games_missed_per_82",
            ]
        ), None

    summary = pd.DataFrame(rows).sort_values("games_missed_per_82")
    treated_val = None
    if treated_id is not None:
        mask = summary["player_id"] == treated_id
        if mask.any():
            treated_val = float(summary.loc[mask, "games_missed_per_82"].iloc[0])
    return summary, treated_val


def permutation_e1(
    summary: pd.DataFrame,
    treated_id: str,
    n_perm: int = 5000,
    cohort: str = "cohort",
) -> tuple[float, np.ndarray, float]:
    """Permutation test for E1: does treated player have unusual games_missed_per_82?

    Test statistic: treated_value - median(others).
    Returns (observed_gap, null_distribution, permutation_p).
    """
    vals = summary["games_missed_per_82"].values.astype(float)
    pids = summary["player_id"].values
    n = len(vals)

    treated_mask = pids == treated_id
    if not treated_mask.any():
        logger.warning("treated_id %s not in summary; skipping permutation.", treated_id)
        return float("nan"), np.array([]), float("nan")

    treated_val = float(vals[treated_mask][0])
    others = vals[~treated_mask]
    observed_gap = treated_val - float(np.median(others))

    rng = np.random.default_rng(42)
    null = np.empty(n_perm)
    for i in range(n_perm):
        # Reassign treatment to one random player; that player is excluded from others
        perm_idx = int(rng.integers(0, n))
        fake_treated_val = vals[perm_idx]
        fake_others = np.delete(vals, perm_idx)
        null[i] = fake_treated_val - np.median(fake_others)

    # Two-sided: fraction of null |gap| >= |observed|
    p_val = float(np.mean(np.abs(null) >= np.abs(observed_gap)))

    # Save null distribution
    null_df = pd.DataFrame({"null_gap": null})
    null_df.to_parquet(DATA_DIR / f"e1_{cohort}_permutation.parquet", index=False)
    logger.info("E1 permutation null saved to data/e1_%s_permutation.parquet", cohort)

    return observed_gap, null, p_val


def compute_e3(
    df: pd.DataFrame,
    treated_id: str | None,
) -> pd.DataFrame:
    """E3: shot-selection differences (3PA/FGA, FTA/FGA) back-to-back vs rest.

    Returns per-player difference table.
    """
    logger.info(
        "Note: conditioning on B2B games selects healthier player-states; "
        "within-player pairing removes stable effects but not state selection."
    )

    rows = []
    for pid, pdata in df.groupby("player_id"):
        name = pdata["player_name"].iloc[0] if "player_name" in pdata.columns else pid

        # Numeric coerce
        for col in ["3PA", "FGA", "FTA"]:
            pdata[col] = pd.to_numeric(pdata[col], errors="coerce")

        pdata = pdata.dropna(subset=["3PA", "FGA", "FTA", "b2b"])
        pdata = pdata[pdata["FGA"] > 0].copy()
        pdata["ratio_3pa_fga"] = pdata["3PA"] / pdata["FGA"]
        pdata["ratio_fta_fga"] = pdata["FTA"] / pdata["FGA"]

        b2b = pdata[pdata["b2b"] == 1]
        rest = pdata[pdata["b2b"] == 0]

        if len(b2b) < 5 or len(rest) < 5:
            continue

        diff_3pa = float(b2b["ratio_3pa_fga"].mean() - rest["ratio_3pa_fga"].mean())
        diff_fta = float(b2b["ratio_fta_fga"].mean() - rest["ratio_fta_fga"].mean())
        rows.append(
            {
                "player_id": pid,
                "player_name": name,
                "b2b_games": len(b2b),
                "rest_games": len(rest),
                "diff_3pa_fga": diff_3pa,
                "diff_fta_fga": diff_fta,
            }
        )

    return pd.DataFrame(rows)


def cohens_d(values: np.ndarray, reference: float) -> float:
    """Effect size: distance of reference from values in SD units."""
    if len(values) < 2:
        return float("nan")
    return (reference - float(np.mean(values))) / float(np.std(values, ddof=1))


def plot_e1_histogram(
    summary: pd.DataFrame,
    treated_id: str | None,
    treated_name: str | None,
    cohort: str,
) -> None:
    """Histogram of games-missed-per-82 with treated player labeled."""
    fig_dir = DATA_DIR / "figures" / cohort
    fig_dir.mkdir(parents=True, exist_ok=True)

    vals = summary["games_missed_per_82"].values
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.hist(vals, bins=min(len(summary), 15), edgecolor="white", color="#4C72B0", alpha=0.8)
    ax.set_xlabel("Games missed per 82")
    ax.set_ylabel("Player count")
    ax.set_title(f"E1: Career durability — {cohort.upper()} cohort (n={len(summary)})")

    if treated_id is not None:
        mask = summary["player_id"] == treated_id
        if mask.any():
            tx = float(summary.loc[mask, "games_missed_per_82"].iloc[0])
            ax.axvline(tx, color="crimson", linewidth=2, label=treated_name)
            ax.legend()

    fig.tight_layout()
    out = fig_dir / "e1_histogram.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    logger.info("Saved %s", out)


def plot_e3_scatter(
    e3_df: pd.DataFrame,
    treated_id: str | None,
    treated_name: str | None,
    cohort: str,
) -> None:
    """Scatter: B2B vs rest 3PA/FGA differences."""
    fig_dir = DATA_DIR / "figures" / cohort
    fig_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(8, 5))
    colors = ["crimson" if pid == treated_id else "#4C72B0" for pid in e3_df["player_id"]]
    ax.scatter(e3_df["diff_3pa_fga"], e3_df["diff_fta_fga"], c=colors, s=60, alpha=0.8)
    ax.axhline(0, color="gray", linewidth=0.8, linestyle="--")
    ax.axvline(0, color="gray", linewidth=0.8, linestyle="--")
    ax.set_xlabel("B2B − rest: Δ(3PA/FGA)")
    ax.set_ylabel("B2B − rest: Δ(FTA/FGA)")
    ax.set_title(f"E3: Shot selection on B2Bs vs rest — {cohort.upper()} cohort")

    if treated_id is not None:
        mask = e3_df["player_id"] == treated_id
        if mask.any():
            tx = float(e3_df.loc[mask, "diff_3pa_fga"].iloc[0])
            ty = float(e3_df.loc[mask, "diff_fta_fga"].iloc[0])
            ax.annotate(
                treated_name,
                (tx, ty),
                textcoords="offset points",
                xytext=(8, 4),
                fontsize=9,
                color="crimson",
            )

    fig.tight_layout()
    out = fig_dir / "e3_scatter.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    logger.info("Saved %s", out)


def emit_comparators_csv(
    summary: pd.DataFrame,
    treated_id: str,
    cohort: str,
    n_comps: int = 3,
) -> None:
    """Emit top-N comparators closest in games_missed_per_82 to treated player."""
    mask = summary["player_id"] == treated_id
    if not mask.any():
        logger.warning("Treated player %s not found; skipping comparators CSV.", treated_id)
        return

    treated_val = float(summary.loc[mask, "games_missed_per_82"].iloc[0])
    others = summary[~mask].copy()
    others["dist"] = (others["games_missed_per_82"] - treated_val).abs()
    comps = others.nsmallest(n_comps, "dist").reset_index(drop=True)
    comps["rank"] = comps.index + 1

    out_cols = ["player_name", "player_id", "games_missed_per_82", "rank"]
    out = DATA_DIR / f"{cohort}_comparators.csv"
    comps[out_cols].to_csv(out, index=False)
    logger.info("Saved %s with %d comparators", out, n_comps)
    logger.info("\n%s", comps[out_cols].to_string(index=False))


def run(cohort: str, n_perm: int = 5000) -> None:
    """Main analysis entry point for one cohort."""
    df, treated_id, treated_name = load_cohort(cohort)

    # ── E1: Career durability ──
    logger.info("\n=== E1: Career durability ===")
    e1_summary, treated_gmiss = compute_e1(df, treated_id)
    logger.info("\n%s\n", e1_summary.to_string(index=False))

    n_ref = len(e1_summary)
    if treated_id and treated_gmiss is not None:
        pct_rank = float(
            stats.percentileofscore(e1_summary["games_missed_per_82"].values, treated_gmiss)
        )
        logger.info(
            "%s: %.2f games missed per 82 — percentile %.1f%% "
            "(n=%d reference class; scope: durability among players with ≥600 career games)",
            treated_name,
            treated_gmiss,
            pct_rank,
            n_ref,
        )

        if n_ref >= 2:
            obs_gap, null_dist, p_perm = permutation_e1(e1_summary, treated_id, n_perm, cohort)
            logger.info(
                "E1 permutation: observed gap = %.3f, two-sided p = %.3f (n_perm=%d)",
                obs_gap,
                p_perm,
                n_perm,
            )

        # Selection bias caveat
        logger.info(
            "\nCohort selected on ≥600 games — E1 estimand scope is durability among "
            "players who completed a long career, not all players."
        )

    # ── E3: Shot selection B2B vs rest ──
    logger.info("\n=== E3: Shot selection (B2B vs rest) ===")
    e3_df = compute_e3(df, treated_id)

    if not e3_df.empty:
        logger.info("\n%s\n", e3_df.to_string(index=False))

        if treated_id is not None:
            mask = e3_df["player_id"] == treated_id
            if mask.any():
                t3pa = float(e3_df.loc[mask, "diff_3pa_fga"].iloc[0])
                tfta = float(e3_df.loc[mask, "diff_fta_fga"].iloc[0])
                cohort_3pa = e3_df["diff_3pa_fga"].values
                cohort_fta = e3_df["diff_fta_fga"].values
                pct_3pa = float(stats.percentileofscore(cohort_3pa, t3pa))
                pct_fta = float(stats.percentileofscore(cohort_fta, tfta))
                d_3pa = cohens_d(cohort_3pa, t3pa)
                d_fta = cohens_d(cohort_fta, tfta)
                logger.info(
                    "%s E3: Δ(3PA/FGA) = %.3f (pct %.1f%%, d=%.2f); "
                    "Δ(FTA/FGA) = %.3f (pct %.1f%%, d=%.2f)",
                    treated_name,
                    t3pa,
                    pct_3pa,
                    d_3pa,
                    tfta,
                    pct_fta,
                    d_fta,
                )
    else:
        logger.warning("E3: no players had sufficient B2B/rest game counts.")

    # ── Figures ──
    if not e1_summary.empty:
        plot_e1_histogram(e1_summary, treated_id, treated_name, cohort)
    if not e3_df.empty:
        plot_e3_scatter(e3_df, treated_id, treated_name, cohort)

    # ── Comparators CSV (pg and pf cohorts) ──
    if treated_id and cohort in ("pg", "pf") and len(e1_summary) >= 4:
        emit_comparators_csv(e1_summary, treated_id, cohort)

    # ── Population-specific outputs ──
    if cohort == "population" and not e1_summary.empty:
        top10 = e1_summary.nsmallest(10, "games_missed_per_82")
        bot10 = e1_summary.nlargest(10, "games_missed_per_82")
        outliers = pd.concat([top10, bot10]).drop_duplicates("player_id")
        outliers.to_csv(DATA_DIR / "population_outliers.csv", index=False)
        logger.info("Saved data/population_outliers.csv")

        for label_id, label_name in [("stockjo01", "Stockton"), ("diawbo01", "Diaw")]:
            mask = e1_summary["player_id"] == label_id
            if mask.any():
                val = float(e1_summary.loc[mask, "games_missed_per_82"].iloc[0])
                pct = float(stats.percentileofscore(e1_summary["games_missed_per_82"].values, val))
                logger.info(
                    "%s: %.2f games missed/82, %.1f%% percentile (era-adjusted)",
                    label_name,
                    val,
                    pct,
                )

        logger.info(
            "\nPopulation conditioned on ≥600 games; E1 estimand scope is durability "
            "among players who completed a long career. Truncated distribution — "
            "interpret percentile ranks with this in mind."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cohort",
        required=True,
        choices=["pg", "pf", "population"],
        help="Which cohort to analyze",
    )
    parser.add_argument(
        "--n-perm", type=int, default=5000, help="Number of permutations for null distribution"
    )
    args = parser.parse_args()
    run(cohort=args.cohort, n_perm=args.n_perm)
