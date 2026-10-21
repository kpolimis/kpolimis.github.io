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
import seaborn as sns

DATA_DIR = pathlib.Path(__file__).parent / "data"

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

MIN_GAMES = 400  # BRef qualifying minimum for career rate statistics


def _ensure_dirs() -> None:
    """Create required data directories if absent."""
    DATA_DIR.mkdir(exist_ok=True)


def _parse_mp(mp_str: str) -> float | None:
    """Convert 'MM:SS' to fractional minutes; returns None for non-playing rows.

    Args:
        mp_str: Minutes-played string in 'MM:SS' format.

    Returns:
        Fractional minutes as float, or None if unparseable.
    """
    if not isinstance(mp_str, str) or ":" not in mp_str:
        return None
    try:
        m, s = mp_str.split(":")
        return int(m) + int(s) / 60
    except ValueError:
        return None


def load_cohort(cohort: str) -> tuple[pd.DataFrame, str | None, str | None]:
    """Load and filter game logs for the given cohort.

    Args:
        cohort: One of 'pg', 'pf', or 'population'.

    Returns:
        Tuple of (df, treated_player_id, treated_player_name).
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
        game_counts = df.groupby("player_id").size()
        eligible = set(game_counts[game_counts >= MIN_GAMES].index)
        df = df[df["player_id"].isin(eligible)].copy()
        logger.info(
            "Population filtered to ≥%d active career games "
            "(BRef qualifying minimum for career rate statistics)",
            MIN_GAMES,
        )

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

    Args:
        df: Game log DataFrame with player_id, season, Date columns.
        treated_id: Player ID to extract treated value for, or None.

    Returns:
        Tuple of (summary_df, treated_gmiss_per_82).
        summary_df columns: player_id, player_name, career_seasons,
        total_season_games, active_games, games_missed, games_missed_per_82.
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

    Args:
        summary: E1 summary DataFrame with player_id and games_missed_per_82 columns.
        treated_id: Player ID to treat as the treatment unit.
        n_perm: Number of permutation resamples.
        cohort: Label used for naming the output parquet.

    Returns:
        Tuple of (observed_gap, null_distribution, permutation_p).
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

    Args:
        df: Game log DataFrame with 3PA, FGA, FTA, b2b columns.
        treated_id: Player ID for the treated unit (used only for logging context).

    Returns:
        Per-player difference table with columns player_id, player_name,
        b2b_games, rest_games, diff_3pa_fga, diff_fta_fga.
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
    """Effect size: distance of reference from values in SD units.

    Args:
        values: Array of comparison values.
        reference: The reference value to compare against the distribution.

    Returns:
        Cohen's d effect size, or nan if fewer than 2 values.
    """
    if len(values) < 2:
        return float("nan")
    return (reference - float(np.mean(values))) / float(np.std(values, ddof=1))


def plot_e1_histogram(
    summary: pd.DataFrame,
    treated_id: str | None,
    treated_name: str | None,
    cohort: str,
) -> None:
    """Histogram of games-missed-per-82 with treated player labeled.

    Args:
        summary: E1 summary DataFrame with games_missed_per_82 column.
        treated_id: Player ID to mark with a vertical line, or None.
        treated_name: Display name for the treated player legend label.
        cohort: Cohort label used for figure directory and title.
    """
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
    """Scatter: B2B vs rest 3PA/FGA and FTA/FGA differences.

    Args:
        e3_df: E3 per-player difference DataFrame.
        treated_id: Player ID to highlight in red, or None.
        treated_name: Display name for annotation label.
        cohort: Cohort label used for figure directory and title.
    """
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
    """Emit top-N comparators closest in games_missed_per_82 to treated player.

    Args:
        summary: E1 summary DataFrame.
        treated_id: Player ID of the treated unit.
        cohort: Cohort label used for the output filename.
        n_comps: Number of closest comparators to include.
    """
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


def _run_e1(
    df: pd.DataFrame,
    treated_id: str | None,
    treated_name: str | None,
    cohort: str,
    n_perm: int,
) -> pd.DataFrame:
    """Run E1 career durability analysis: compute, log, run permutation test.

    Args:
        df: Filtered game log DataFrame for the cohort.
        treated_id: Player ID of the treated unit, or None for population.
        treated_name: Display name for logging, or None.
        cohort: Cohort label used for permutation parquet naming.
        n_perm: Number of permutation resamples.

    Returns:
        E1 summary DataFrame sorted by games_missed_per_82.
    """
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
            "(n=%d reference class; scope: durability among players with ≥400 career games, "
            "the BRef qualifying minimum for career rate statistics)",
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
            "\nCohort selected on ≥400 career games (BRef qualifying minimum for career "
            "rate statistics) — E1 estimand scope is durability among players who "
            "completed a long career, not all players."
        )

    return e1_summary


def _run_e3(
    df: pd.DataFrame,
    treated_id: str | None,
    treated_name: str | None,
) -> pd.DataFrame:
    """Run E3 shot-selection analysis: compute and log effect sizes.

    Args:
        df: Filtered game log DataFrame for the cohort.
        treated_id: Player ID of the treated unit, or None.
        treated_name: Display name for logging, or None.

    Returns:
        E3 per-player difference DataFrame.
    """
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

    return e3_df


def _save_population_outputs(
    e1_summary: pd.DataFrame,
    label: str,
    min_games: int,
) -> None:
    """Save population outliers CSV and log percentile ranks for E7_TREATED players.

    Args:
        e1_summary: E1 summary DataFrame with games_missed_per_82 column.
        label: Output label — 'population' for primary, 'population_N' for sensitivity.
        min_games: Active-game threshold used for this pass (for log message).
    """
    top10 = e1_summary.nsmallest(10, "games_missed_per_82")
    bot10 = e1_summary.nlargest(10, "games_missed_per_82")
    outliers = pd.concat([top10, bot10]).drop_duplicates("player_id")
    if label == "population":
        outliers_path = DATA_DIR / "population_outliers.csv"
    else:
        sens_dir = DATA_DIR / "figures" / label
        sens_dir.mkdir(parents=True, exist_ok=True)
        outliers_path = sens_dir / "population_outliers.csv"
    outliers.to_csv(outliers_path, index=False)
    logger.info("Saved %s", outliers_path)

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
        "\nPopulation conditioned on ≥%d career games (primary threshold 400 is the "
        "BRef qualifying minimum for career rate statistics); E1 estimand scope is "
        "durability among players who completed a long career. Truncated "
        "distribution — interpret percentile ranks with this in mind.",
        min_games,
    )


def run(cohort: str, n_perm: int = 5000, min_games: int = MIN_GAMES) -> None:
    """Main analysis entry point for one cohort.

    For the population cohort, min_games sets the active-game eligibility floor
    (default MIN_GAMES=400, the BRef qualifying minimum for career rate
    statistics). Sensitivity runs (600, 820) write outputs to suffixed
    directories so they never overwrite the primary run.

    Args:
        cohort: One of 'pg', 'pf', or 'population'.
        n_perm: Number of permutation resamples for E1.
        min_games: Active-game floor for population cohort filtering.
    """
    _ensure_dirs()
    df, treated_id, treated_name = load_cohort(cohort)

    label = cohort
    if cohort == "population":
        game_counts = df.groupby("player_id").size()
        eligible = set(game_counts[game_counts >= min_games].index)
        df = df[df["player_id"].isin(eligible)].copy()
        if min_games != MIN_GAMES:
            label = f"{cohort}_{min_games}"
        logger.info(
            "Population E1/E3 pass: ≥%d active career games — %d players",
            min_games,
            df["player_id"].nunique(),
        )

    e1_summary = _run_e1(df, treated_id, treated_name, cohort, n_perm)
    e3_df = _run_e3(df, treated_id, treated_name)

    if not e1_summary.empty:
        plot_e1_histogram(e1_summary, treated_id, treated_name, label)
    if not e3_df.empty:
        plot_e3_scatter(e3_df, treated_id, treated_name, label)

    if treated_id and cohort in ("pg", "pf") and len(e1_summary) >= 4:
        emit_comparators_csv(e1_summary, treated_id, cohort)

    if cohort == "population" and not e1_summary.empty:
        _save_population_outputs(e1_summary, label, min_games)


E7_METRICS = ["TS_pct", "eFG_pct", "FTA_rate", "3PA_rate"]
E7_TREATED = [("stockjo01", "Stockton"), ("diawbo01", "Diaw")]


def _load_e7_data() -> tuple[pd.DataFrame, pd.Series]:
    """Load game log columns needed for E7 and coerce numeric types.

    Returns:
        Tuple of (df, games) where games is a Series of per-player row counts.
    """
    parquet = DATA_DIR / "game_logs.parquet"
    if not parquet.exists():
        raise FileNotFoundError("data/game_logs.parquet not found — run fetch_bref_data.py first.")

    df = pd.read_parquet(
        parquet,
        columns=[
            "player_id",
            "player_name",
            "season",
            "PTS",
            "FG",
            "FGA",
            "3P",
            "3PA",
            "FT",
            "FTA",
        ],
    )
    for col in ["PTS", "FG", "FGA", "3P", "3PA", "FT", "FTA"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # Pre-1980 era had no 3PA tracked — treat missing attempts as zero
    df["3P"] = df["3P"].fillna(0)
    df["3PA"] = df["3PA"].fillna(0)

    games = df.groupby("player_id").size()
    return df, games


def _apply_tsa_threshold(
    df: pd.DataFrame,
    games: pd.Series,
    min_tsa: int,
    min_games: int | None,
) -> pd.DataFrame:
    """Filter df to players meeting career TSA and optional games thresholds.

    Args:
        df: Full game log DataFrame.
        games: Series of per-player total row counts (index = player_id).
        min_tsa: Minimum career true-shot attempts (FGA + 0.44·FTA).
        min_games: Optional minimum career game count; None skips this filter.

    Returns:
        Filtered DataFrame containing only qualifying players.
    """
    career_totals = df.groupby("player_id")[["FGA", "FTA"]].sum()
    career_tsa = career_totals["FGA"] + 0.44 * career_totals["FTA"]
    eligible = set(career_tsa[career_tsa >= min_tsa].index)
    if min_tsa > 0:
        logger.info(
            "E7 eligibility: ≥%s TSA — BRef career TS%% qualifying minimum (5,000 TSA)",
            f"{min_tsa:,}",
        )
    if min_games is not None:
        eligible &= set(games[games >= min_games].index)
        logger.info("E7 eligibility: additional ≥%d games constraint applied", min_games)
    return df[df["player_id"].isin(eligible)].copy()


def _compute_ts_per_player(df: pd.DataFrame, games: pd.Series) -> pd.DataFrame:
    """Aggregate per-player career shooting stats into a TS% table.

    Args:
        df: Filtered game log DataFrame (only qualifying players).
        games: Series of per-player total row counts (index = player_id).

    Returns:
        DataFrame with one row per player: player_id, player_name, games,
        seasons, debut_year, final_year, TS_pct, eFG_pct, FTA_rate, 3PA_rate.
    """
    rows = []
    for pid, pdata in df.groupby("player_id"):
        shot = pdata[pdata["FGA"] > 0]
        fga, fta = shot["FGA"].sum(), shot["FTA"].sum()
        pts, fg, tp, tpa = shot["PTS"].sum(), shot["FG"].sum(), shot["3P"].sum(), shot["3PA"].sum()
        rows.append(
            {
                "player_id": pid,
                "player_name": pdata["player_name"].iloc[0],
                "games": int(games[pid]),
                "seasons": int(pdata["season"].nunique()),
                "debut_year": int(pdata["season"].min()),
                "final_year": int(pdata["season"].max()),
                "TS_pct": pts / (2 * (fga + 0.44 * fta)),
                "eFG_pct": (fg + 0.5 * tp) / fga,
                "FTA_rate": fta / fga,
                "3PA_rate": tpa / fga,
            }
        )
    return pd.DataFrame(rows).sort_values("TS_pct", ascending=False).reset_index(drop=True)


def compute_e7_career_shooting(
    min_tsa: int = 5000,
    min_games: int | None = None,
) -> pd.DataFrame:
    """E7: Career shooting-efficiency table for qualifying players.

    Primary eligibility is career true-shot attempts (TSA = FGA + 0.44·FTA) ≥ min_tsa,
    the BRef career TS% qualifying minimum (5,000 TSA). min_games, when given, is an
    optional additional games-played constraint. Aggregates career totals (rows with
    FGA > 0) into TS%, eFG%, FTA/FGA, 3PA/FGA, plus empirical percentile ranks
    (0–100) within the qualifying population.

    Args:
        min_tsa: Minimum career true-shot attempts for eligibility.
        min_games: Optional minimum career games played.

    Returns:
        DataFrame sorted descending by TS_pct with percentile rank columns.
    """
    df, games = _load_e7_data()
    df = _apply_tsa_threshold(df, games, min_tsa, min_games)
    shooting = _compute_ts_per_player(df, games)
    for metric in E7_METRICS:
        shooting[f"{metric}_pctile"] = shooting[metric].rank(pct=True, method="average") * 100
    return shooting


def plot_e7_ts_distribution(
    shooting: pd.DataFrame,
    fig_subdir: str = "population",
    pop_label: str = "≥5,000-TSA population",
) -> None:
    """KDE + rug of career TS% with Stockton and Diaw marked.

    Args:
        shooting: E7 shooting DataFrame with TS_pct and player_id columns.
        fig_subdir: Subdirectory under data/figures/ for the output PNG.
        pop_label: Population description for the figure title.
    """
    fig_dir = DATA_DIR / "figures" / fig_subdir
    fig_dir.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(8, 5))
    sns.kdeplot(x=shooting["TS_pct"], fill=True, color="#4C72B0", alpha=0.4, ax=ax)
    sns.rugplot(x=shooting["TS_pct"], color="#4C72B0", alpha=0.4, ax=ax)

    for (pid, label), color in zip(E7_TREATED, ["crimson", "darkorange"], strict=False):
        mask = shooting["player_id"] == pid
        if mask.any():
            tx = float(shooting.loc[mask, "TS_pct"].iloc[0])
            ax.axvline(tx, color=color, linewidth=2, linestyle="--", label=f"{label} ({tx:.3f})")

    ax.set_xlabel("Career true shooting % (TS%)")
    ax.set_ylabel("Density")
    ax.set_title(f"E7: Career TS% distribution — {pop_label} (n={len(shooting)})")
    ax.legend()

    fig.tight_layout()
    out = fig_dir / "e7_ts_pct_distribution.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    logger.info("Saved %s", out)


def plot_e7_ts_vs_fta_rate(
    shooting: pd.DataFrame,
    fig_subdir: str = "population",
    pop_label: str = "≥5,000-TSA population",
) -> None:
    """Scatter: career TS% vs FTA/FGA rate with Stockton and Diaw labeled.

    Args:
        shooting: E7 shooting DataFrame with TS_pct, FTA_rate, and player_id columns.
        fig_subdir: Subdirectory under data/figures/ for the output PNG.
        pop_label: Population description for the figure title.
    """
    fig_dir = DATA_DIR / "figures" / fig_subdir
    fig_dir.mkdir(parents=True, exist_ok=True)

    treated_ids = {pid for pid, _ in E7_TREATED}
    others = shooting[~shooting["player_id"].isin(treated_ids)]

    fig, ax = plt.subplots(figsize=(8, 5))
    ax.scatter(others["FTA_rate"], others["TS_pct"], c="#4C72B0", s=30, alpha=0.5)

    for pid, label in E7_TREATED:
        mask = shooting["player_id"] == pid
        if mask.any():
            tx = float(shooting.loc[mask, "FTA_rate"].iloc[0])
            ty = float(shooting.loc[mask, "TS_pct"].iloc[0])
            ax.scatter([tx], [ty], c="crimson", s=80, zorder=3)
            ax.annotate(
                label,
                (tx, ty),
                textcoords="offset points",
                xytext=(8, 4),
                fontsize=9,
                color="crimson",
            )

    ax.set_xlabel("Career FTA/FGA rate")
    ax.set_ylabel("Career TS%")
    ax.set_title(f"E7: TS% vs free-throw rate — {pop_label} (n={len(shooting)})")

    fig.tight_layout()
    out = fig_dir / "e7_scatter_ts_fta_rate.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    logger.info("Saved %s", out)


def _log_e7_player_stats(shooting: pd.DataFrame, n: int) -> None:
    """Log per-player E7 metrics for all E7_TREATED players.

    Args:
        shooting: E7 shooting DataFrame with metric and percentile columns.
        n: Total number of players in the qualifying population.
    """
    metric_labels = {
        "TS_pct": "TS%",
        "eFG_pct": "eFG%",
        "FTA_rate": "FTA/FGA",
        "3PA_rate": "3PA/FGA",
    }
    for pid, label in E7_TREATED:
        mask = shooting["player_id"] == pid
        if not mask.any():
            logger.warning("%s (%s) not in qualifying population; skipping.", label, pid)
            continue
        logger.info("\n%s (%s):", label, pid)
        for metric in E7_METRICS:
            obs = float(shooting.loc[mask, metric].iloc[0])
            pctile = float(shooting.loc[mask, f"{metric}_pctile"].iloc[0])
            rank = int((shooting[metric] > obs).sum()) + 1  # 1 = highest
            p_geq = float((shooting[metric] >= obs).mean())
            logger.info(
                "  %-9s %.3f  (pctile: %.1f, rank %d/%d, p[>=obs]=%.3f)",
                metric_labels[metric] + ":",
                obs,
                pctile,
                rank,
                n,
                p_geq,
            )


def _run_e7_pass(
    min_tsa: int,
    min_games: int | None,
    header: str,
    csv_name: str,
    fig_subdir: str,
    pop_label: str,
) -> pd.DataFrame:
    """One E7 pass: compute table, write CSV, log stats, render figures.

    Rank-based test on the empirical distribution: each of the n players is a draw
    from the null; p = fraction of players with metric ≥ observed (one-tailed,
    "at least as efficient"). No resampling needed — the population IS the null.

    Args:
        min_tsa: Minimum career TSA for eligibility.
        min_games: Optional minimum career games played.
        header: Label string for log output header.
        csv_name: Filename for the output CSV (under data/).
        fig_subdir: Figure subdirectory under data/figures/.
        pop_label: Population description used in figure titles.

    Returns:
        E7 shooting DataFrame for this pass.
    """
    shooting = compute_e7_career_shooting(min_tsa=min_tsa, min_games=min_games)
    n = len(shooting)

    out_cols = ["player_id", "player_name", "games", "seasons", "debut_year", "final_year"]
    out_cols += E7_METRICS + [f"{m}_pctile" for m in E7_METRICS]
    out = DATA_DIR / csv_name
    shooting[out_cols].to_csv(out, index=False)
    logger.info("Saved %s (%d players)", out, n)

    ts = shooting["TS_pct"]
    logger.info("\n--- %s, n=%d) ---", header, n)
    logger.info(
        "Population TS%%: mean=%.3f, sd=%.3f, range=[%.3f, %.3f]",
        ts.mean(),
        ts.std(ddof=1),
        ts.min(),
        ts.max(),
    )

    _log_e7_player_stats(shooting, n)
    plot_e7_ts_distribution(shooting, fig_subdir=fig_subdir, pop_label=pop_label)
    plot_e7_ts_vs_fta_rate(shooting, fig_subdir=fig_subdir, pop_label=pop_label)
    return shooting


def analyze_e7_shooting_efficiency(
    min_tsa: int = 5000,
    min_games: int | None = None,
) -> pd.DataFrame:
    """E7: Career shooting efficiency — primary (TSA) pass plus two sensitivity passes.

    Primary: min_tsa (default 5,000 TSA, the BRef career TS% qualifying minimum),
    with min_games as an optional additional constraint. Sensitivity A re-runs on a
    ≥400-game cohort (BRef rate stat threshold); sensitivity B on a ≥820-game cohort
    (10-year veteran). Returns the primary pass table.

    Args:
        min_tsa: Minimum career TSA for the primary pass.
        min_games: Optional minimum career games for the primary pass.

    Returns:
        Primary pass E7 shooting DataFrame.
    """
    logger.info("\n=== E7: Career Shooting Efficiency ===")

    primary = _run_e7_pass(
        min_tsa=min_tsa,
        min_games=min_games,
        header=f"Primary: ≥{min_tsa:,} TSA (BRef TS% standard",
        csv_name="e7_career_shooting.csv",
        fig_subdir="population",
        pop_label=f"≥{min_tsa:,}-TSA population",
    )
    _run_e7_pass(
        min_tsa=0,
        min_games=400,
        header="Sensitivity A: ≥400 games (BRef rate stat threshold",
        csv_name="e7_career_shooting_s400.csv",
        fig_subdir="population_s400",
        pop_label="≥400-game population",
    )
    _run_e7_pass(
        min_tsa=0,
        min_games=820,
        header="Sensitivity B: ≥820 games (10-year veteran",
        csv_name="e7_career_shooting_s820.csv",
        fig_subdir="population_s820",
        pop_label="≥820-game population",
    )
    return primary


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
    if args.cohort == "population":
        run("population", n_perm=args.n_perm, min_games=400)
        run("population", n_perm=args.n_perm, min_games=600)
        run("population", n_perm=args.n_perm, min_games=820)
        analyze_e7_shooting_efficiency()
    else:
        run(cohort=args.cohort, n_perm=args.n_perm)
