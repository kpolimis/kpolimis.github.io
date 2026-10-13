"""analyze_quarter_splits.py — E2/E4/E5 within-game analysis.

E2: 4Q FT% degradation (mixed-effects model + permutation CI)
E4: 4Q AST/TOV ratio
E5: 4Q TS%

All estimands require quarter-level stats from fetch_quarter_splits.py.
PF cohort → reads data/quarter_splits_pf.parquet (full Diaw career)
PG cohort → reads data/quarter_splits_pg.parquet (Stockton 1996–2003)

Usage:
    conda run -n blog python analyze_quarter_splits.py --cohort pf
    conda run -n blog python analyze_quarter_splits.py --cohort pg
"""

import argparse
import logging
import pathlib
import warnings

import matplotlib
import numpy as np
import pandas as pd
from statsmodels.regression.mixed_linear_model import MixedLM

matplotlib.use("Agg")
import matplotlib.pyplot as plt

DATA_DIR = pathlib.Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def load_splits(cohort: str) -> tuple[pd.DataFrame, str | None, str | None]:
    """Load quarter splits parquet and return (df, treated_id, treated_name)."""
    if cohort not in ("pg", "pf"):
        raise ValueError(f"Unknown cohort: {cohort!r}. Use pg or pf.")

    parquet = DATA_DIR / f"quarter_splits_{cohort}.parquet"
    if not parquet.exists():
        raise FileNotFoundError(
            f"data/quarter_splits_{cohort}.parquet not found — run fetch_quarter_splits.py first."
        )
    df = pd.read_parquet(parquet)
    logger.info("Loaded %s rows from quarter_splits_%s.parquet", f"{len(df):,}", cohort)

    if cohort == "pg":
        treated_id, treated_name = "stockjo01", "John Stockton"
        # Issue #29: age-regime caveat
        logger.info(
            "Analysis window is Stockton ages 34–40. A null result in this window does not "
            "contradict a peak-workload resilience claim during his prime (ages 22–34)."
        )
    elif cohort == "pf":
        treated_id, treated_name = "diawbo01", "Boris Diaw"
    else:
        raise ValueError(f"Unknown cohort: {cohort!r}")

    return df, treated_id, treated_name


def _prepare_model_df(
    df: pd.DataFrame,
    metric_col: str,
    treated_id: str,
) -> pd.DataFrame | None:
    """Prepare DataFrame for mixed-effects model.

    Joins rest_days from game_logs if available, creates is_treated and quarter4 flags.
    Returns None if insufficient data.
    """
    required = [metric_col, "player_id", "quarter", "season", "date"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        logger.warning("Missing columns %s — cannot fit model for %s", missing, metric_col)
        return None

    mdf = df.dropna(subset=[metric_col]).copy()
    mdf["is_treated"] = (mdf["player_id"] == treated_id).astype(int)
    mdf["quarter4"] = (mdf["quarter"].astype(str) == "4").astype(int)

    # Merge rest_days from game_logs only if not already present
    if "rest_days" not in mdf.columns:
        gl_path = DATA_DIR / "game_logs.parquet"
        if gl_path.exists():
            gl = pd.read_parquet(gl_path)[["player_id", "Date", "rest_days"]].copy()
            gl["date"] = pd.to_datetime(gl["Date"])
            mdf["date"] = pd.to_datetime(mdf["date"])
            mdf = mdf.merge(
                gl[["player_id", "date", "rest_days"]], on=["player_id", "date"], how="left"
            )
            mdf["rest_days"] = mdf["rest_days"].fillna(3)
        else:
            mdf["rest_days"] = 3.0
    else:
        mdf["rest_days"] = mdf["rest_days"].fillna(3)

    if len(mdf) < 20 or mdf["player_id"].nunique() < 2:
        logger.warning(
            "Insufficient data for %s model: %d rows, %d players.",
            metric_col,
            len(mdf),
            mdf["player_id"].nunique(),
        )
        return None

    # Drop 'full'-game summary rows; we only want per-quarter rows for Q4 analysis
    full_mask = mdf["quarter"].astype(str) == "full"
    if full_mask.all():
        logger.warning(
            "All rows are 'full'-game summaries — no per-quarter BRef PBP data available. "
            "Skipping model for %s.",
            metric_col,
        )
        return None
    if full_mask.any():
        logger.info("Dropping %d 'full'-game rows; keeping per-quarter rows.", full_mask.sum())
        mdf = mdf[~full_mask].copy()

    return mdf


def permutation_interaction(
    mdf: pd.DataFrame,
    metric_col: str,
    n_perm: int = 5000,
    cohort: str = "cohort",
) -> tuple[float, np.ndarray, float]:
    """Permutation CI on the quarter4:is_treated interaction.

    Permutes is_treated label at the player level (not row level).
    Returns (observed_coef, null_distribution, two_sided_p).
    """
    mdf = mdf.copy()
    mdf["quarter4_treated"] = mdf["quarter4"] * mdf["is_treated"]

    def _fit_and_get_coef(df: pd.DataFrame) -> float:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = MixedLM(
                    endog=df[metric_col],
                    exog=pd.concat(
                        [
                            pd.Series(1.0, index=df.index, name="const"),
                            df[["quarter4", "is_treated", "quarter4_treated", "rest_days"]],
                        ],
                        axis=1,
                    ),
                    groups=df["player_id"],
                )
                res = model.fit(reml=True, method="lbfgs", disp=False)
            return float(res.params.get("quarter4_treated", float("nan")))
        except Exception:
            return float("nan")

    obs = _fit_and_get_coef(mdf)
    players = mdf["player_id"].unique()
    rng = np.random.default_rng(42)
    null = []

    for _ in range(n_perm):
        perm_treated = rng.choice(players)
        tmp = mdf.copy()
        tmp["is_treated"] = (tmp["player_id"] == perm_treated).astype(int)
        tmp["quarter4_treated"] = tmp["quarter4"] * tmp["is_treated"]
        c = _fit_and_get_coef(tmp)
        if not np.isnan(c):
            null.append(c)

    null_arr = np.array(null)
    if len(null_arr) == 0 or np.isnan(obs):
        return obs, null_arr, float("nan")

    p_val = float(np.mean(np.abs(null_arr) >= abs(obs)))

    null_df = pd.DataFrame({"null_coef": null_arr})
    out = DATA_DIR / f"e{_estimand_from_metric(metric_col)}_{cohort}_permutation.parquet"
    null_df.to_parquet(out, index=False)
    logger.info("Permutation null saved to %s", out)

    return obs, null_arr, p_val


def _estimand_from_metric(metric: str) -> str:
    mapping = {"FT_pct": "2", "AST_TOV_ratio": "4", "TS_pct": "5"}
    return mapping.get(metric, "x")


def run_estimand(
    df: pd.DataFrame,
    metric_col: str,
    treated_id: str,
    treated_name: str,
    cohort: str,
    n_perm: int,
    extra_caveats: list[str] | None = None,
) -> None:
    """Fit model, run permutation test, and print results for one estimand."""
    estimand_num = _estimand_from_metric(metric_col)
    logger.info("\n=== E%s: %s ===", estimand_num, metric_col)

    # Print required caveats
    logger.info(
        "Late-game stats are confounded by score margin, intentional fouling, "
        "and garbage-time lineups. FT%% (E2) is the least-confounded because "
        "FT shooting is isolated and consistent."
    )
    if extra_caveats:
        for caveat in extra_caveats:
            logger.info(caveat)

    mdf = _prepare_model_df(df, metric_col, treated_id)
    if mdf is None:
        return

    # Fit for permutation baseline
    mdf_fit = mdf.copy()
    mdf_fit["quarter4_treated"] = mdf_fit["quarter4"] * mdf_fit["is_treated"]

    obs_coef, null_dist, p_val = permutation_interaction(mdf_fit, metric_col, n_perm, cohort)

    if not np.isnan(obs_coef):
        ci_lo = float(np.percentile(null_dist, 2.5)) if len(null_dist) > 0 else float("nan")
        ci_hi = float(np.percentile(null_dist, 97.5)) if len(null_dist) > 0 else float("nan")
        logger.info(
            "%s E%s: quarter4:is_treated = %.4f, 95%% perm CI [%.4f, %.4f], p = %.3f",
            treated_name,
            estimand_num,
            obs_coef,
            ci_lo,
            ci_hi,
            p_val,
        )
    else:
        logger.warning("E%s: could not compute coefficient.", estimand_num)


def _add_ast_tov(df: pd.DataFrame) -> pd.DataFrame:
    """Compute AST/TOV ratio, avoiding division by zero."""
    df = df.copy()
    if "AST" in df.columns and "TOV" in df.columns:
        df["AST"] = pd.to_numeric(df["AST"], errors="coerce")
        df["TOV"] = pd.to_numeric(df["TOV"], errors="coerce")
        df["AST_TOV_ratio"] = df["AST"] / (df["TOV"] + 0.001)
    return df


def plot_estimand(
    df: pd.DataFrame,
    metric_col: str,
    treated_id: str | None,
    treated_name: str | None,
    cohort: str,
    estimand_num: str,
    fname: str,
) -> None:
    """Bar/box comparison of metric by quarter and treatment status."""
    fig_dir = DATA_DIR / "figures" / cohort
    fig_dir.mkdir(parents=True, exist_ok=True)

    if metric_col not in df.columns or "quarter" not in df.columns:
        return

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, (is_treated_val, label) in zip(
        axes, [(0, "Cohort"), (1, treated_name or "Treated")], strict=False
    ):
        sub = df[df["player_id"] == treated_id] if is_treated_val == 1 and treated_id else df
        if sub.empty:
            continue
        q_means = sub.groupby("quarter")[metric_col].mean()
        ax.bar(q_means.index.astype(str), q_means.values, color="#4C72B0", alpha=0.8)
        ax.set_title(f"{label}: {metric_col} by quarter")
        ax.set_xlabel("Quarter")
        ax.set_ylabel(metric_col)

    fig.suptitle(f"E{estimand_num}: {cohort.upper()} cohort — {metric_col}")
    fig.tight_layout()
    out = fig_dir / fname
    fig.savefig(out, dpi=150)
    plt.close(fig)
    logger.info("Saved %s", out)


def plot_e6_quarter_profile(
    df: pd.DataFrame,
    treated_id: str | None,
    treated_name: str | None,
    cohort: str,
    fname: str = "e6_quarter_profile.png",
) -> None:
    """E6: FT% across Q1→Q4 for every player in the cohort window."""
    import matplotlib.ticker as mticker

    fig_dir = DATA_DIR / "figures" / cohort
    fig_dir.mkdir(parents=True, exist_ok=True)

    quarters = ["1", "2", "3", "4"]
    df_q = df[df["quarter"].astype(str).isin(quarters)].copy()
    for col in ("FT", "FTA"):
        df_q[col] = pd.to_numeric(df_q[col], errors="coerce")

    agg = (
        df_q.groupby(["player_id", "player_name", "quarter"])
        .agg(FT=("FT", "sum"), FTA=("FTA", "sum"))
        .reset_index()
    )
    agg = agg[agg["FTA"] > 0].copy()
    agg["ft_pct"] = agg["FT"] / agg["FTA"]
    agg["quarter"] = pd.Categorical(agg["quarter"], categories=quarters, ordered=True)
    agg = agg.sort_values("quarter")

    fig, ax = plt.subplots(figsize=(8, 5))
    for pid, grp in agg.groupby("player_id"):
        name = grp["player_name"].iloc[0]
        if pid == treated_id:
            ax.plot(
                grp["quarter"].astype(str),
                grp["ft_pct"],
                color="#E84D3C",
                linewidth=2.5,
                marker="o",
                markersize=7,
                zorder=5,
                label=f"{name} (treated)",
            )
        else:
            ax.plot(
                grp["quarter"].astype(str),
                grp["ft_pct"],
                color="#AAAAAA",
                linewidth=1.5,
                marker="o",
                markersize=4,
                alpha=0.7,
                label=name,
            )

    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax.set_xlabel("Quarter")
    ax.set_ylabel("FT%")
    ax.set_title(f"E6: FT% by quarter — {cohort.upper()} cohort")
    ax.legend(fontsize=9, loc="upper left" if cohort == "pg" else "lower left")
    ax.set_ylim(0.45, 1.0)
    fig.tight_layout()
    out = fig_dir / fname
    fig.savefig(out, dpi=150)
    plt.close(fig)
    logger.info("Saved %s", out)


def run(cohort: str, n_perm: int = 5000) -> None:
    """Main entry point."""
    df, treated_id, treated_name = load_splits(cohort)

    # Prepare metrics
    for col in ["FT", "FTA", "FGA", "PTS", "AST", "TOV", "FT_pct", "TS_pct"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Compute derived metrics
    if "FT_pct" not in df.columns and "FT" in df.columns and "FTA" in df.columns:
        df["FT_pct"] = df.apply(lambda r: r["FT"] / r["FTA"] if r["FTA"] > 0 else np.nan, axis=1)
    if "TS_pct" not in df.columns and "PTS" in df.columns:
        df["TS_pct"] = df.apply(
            lambda r: (
                r["PTS"] / (2 * (r["FGA"] + 0.44 * r.get("FTA", 0)))
                if (r["FGA"] + 0.44 * r.get("FTA", 0)) > 0
                else np.nan
            ),
            axis=1,
        )
    df = _add_ast_tov(df)

    # PG cohort extra caveats (issue #29)
    pg_caveats = None
    if cohort == "pg":
        pg_caveats = [
            "4th-quarter stats are confounded by score margin: starters sit in blowouts, "
            "and minutes are reduced when games are not close. This compresses the treatment "
            "effect estimate toward zero.",
            "Coaches use timeouts strategically in the 4th quarter; a team with more timeouts "
            "grants more recovery time. Timeout-adjusted rest is not available from BRef box "
            "scores and is an unmeasured confounder.",
            "In close games, opponents foul intentionally, artificially inflating FTA counts "
            "in the 4th quarter. FT% estimates in close games may reflect pressure context, "
            "not just physical state.",
        ]

    # ── E2: FT% degradation ──
    run_estimand(df, "FT_pct", treated_id, treated_name, cohort, n_perm, pg_caveats)

    # ── E4: AST/TOV ratio ──
    run_estimand(df, "AST_TOV_ratio", treated_id, treated_name, cohort, n_perm, pg_caveats)

    # ── E5: TS% ──
    run_estimand(df, "TS_pct", treated_id, treated_name, cohort, n_perm, pg_caveats)

    # ── Sensitivity: blowout filter for PG cohort ──
    if cohort == "pg" and "score_margin" in df.columns:
        competitive = df[df["score_margin"].notna() & (df["score_margin"] <= 10)]
        if len(competitive) >= 20:
            logger.info(
                "\n=== E2 sensitivity: competitive games (margin ≤ 10) ===\nRestricted to %d rows.",
                len(competitive),
            )
            run_estimand(
                competitive,
                "FT_pct",
                treated_id,
                treated_name,
                f"{cohort}_competitive",
                n_perm,
                None,
            )
        else:
            logger.info(
                "Score margin data available but only %d competitive-game rows — "
                "skipping sensitivity.",
                len(competitive),
            )
    elif cohort == "pg":
        logger.info(
            "Score margin column not available in quarter_splits_pg.parquet; "
            "blowout sensitivity not run."
        )

    # ── Figures ──
    plot_estimand(df, "FT_pct", treated_id, treated_name, cohort, "2", "e2_q4_ft_degradation.png")
    plot_estimand(df, "AST_TOV_ratio", treated_id, treated_name, cohort, "4", "e4_ast_tov.png")
    plot_estimand(df, "TS_pct", treated_id, treated_name, cohort, "5", "e5_ts_pct.png")
    plot_e6_quarter_profile(df, treated_id, treated_name, cohort)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cohort", required=True, choices=["pg", "pf"], help="Cohort to analyze (pg or pf)"
    )
    parser.add_argument("--n-perm", type=int, default=5000, help="Permutation iterations")
    args = parser.parse_args()
    run(cohort=args.cohort, n_perm=args.n_perm)
