"""Audit Basketball-Reference population fetch against the expected cohort.

Usage: python audit_fetch.py
Writes data/fetch_gaps.csv for a targeted second fetch wave.
"""

import logging
import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
LOW_GAME_THRESHOLD = 20
MAX_LOG = 25  # console cap per section; full detail goes to fetch_gaps.csv
KEY_COLUMNS = ["Date", "MP", "mp_float", "PTS", "player_id", "season", "player_name"]

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)


def _log_capped(lines: list[str]) -> None:
    """Log up to MAX_LOG lines, then summarize the remainder."""
    for line in lines[:MAX_LOG]:
        logger.info(line)
    if len(lines) > MAX_LOG:
        logger.info("  ... and %d more (see fetch_gaps.csv)", len(lines) - MAX_LOG)


def _audit_missing_players(cohort: pd.DataFrame, fetched_ids: set, names: pd.Series) -> list:
    """Report players missing entirely from the fetch; return gap rows."""
    missing = sorted(set(cohort["player_id"]) - fetched_ids)
    logger.info("\n--- Players completely missing: %d ---", len(missing))
    _log_capped([f"  {pid:<12} {names.get(pid, '?')}" for pid in missing])
    return [(pid, names.get(pid, ""), "", "missing_player") for pid in missing]


def _audit_missing_seasons(
    cohort: pd.DataFrame, logs: pd.DataFrame, missing_players: list, names: pd.Series
) -> list:
    """Report season gaps for fetched players; return gap rows."""
    # cohort debut/final years use the same season-ending-year convention as
    # the parquet's `season` column (e.g. 1984-85 season -> 1985)
    seasons_by_player = logs.groupby("player_id")["season"].agg(set)
    missing_season_rows = []
    gaps = []
    for row in cohort.itertuples():
        if row.player_id in missing_players:
            continue
        expected = set(range(row.debut_year, row.final_year + 1))
        have = seasons_by_player.get(row.player_id, set())
        missing = sorted(expected - have)
        if missing:
            missing_season_rows.append((row.player_id, row.player_name, missing))
            gaps.extend((row.player_id, row.player_name, s, "missing_season") for s in missing)
    logger.info("\n--- Players with missing seasons: %d ---", len(missing_season_rows))
    logger.info("(note: a missing mid-career season can be legitimate, e.g. overseas)")
    _log_capped([f"  {pid:<12} {name:<28} missing: {ms}" for pid, name, ms in missing_season_rows])
    return gaps


def _audit_low_game_counts(logs: pd.DataFrame, names: pd.Series) -> list:
    """Report (player, season) pairs with suspiciously few games; return gap rows."""
    game_counts = logs.groupby(["player_id", "season"]).size()
    low = game_counts[game_counts < LOW_GAME_THRESHOLD].sort_index()
    logger.info("\n--- (player, season) pairs with <%d games: %d ---", LOW_GAME_THRESHOLD, len(low))
    logger.info("(flagged for review, not treated as fetch errors)")
    _log_capped(
        [
            f"  {pid:<12} {names.get(pid, '?'):<28} {season}  ({n} games)"
            for (pid, season), n in low.items()
        ]
    )
    return [
        (pid, names.get(pid, ""), season, "low_game_count") for (pid, season), _n in low.items()
    ]


def _audit_null_rates(logs: pd.DataFrame) -> None:
    """Log NULL rates for key columns."""
    logger.info("\n--- NULL rates (key columns) ---")
    for col in KEY_COLUMNS:
        if col not in logs.columns:
            logger.warning("  %s  MISSING FROM PARQUET", col)
            continue
        rate = logs[col].isna().mean()
        logger.info("  %-12s %7.2f%%  (%s nulls)", col, rate * 100, f"{logs[col].isna().sum():,}")


def _log_verdict(missing_players: list, missing_season_gaps: list, low_gaps: list) -> None:
    """Log the summary verdict line."""
    logger.info("\n%s", "=" * 70)
    if missing_players:
        verdict = f"NEEDS SECOND WAVE — {len(missing_players)} players completely missing"
    elif missing_season_gaps:
        n = len(missing_season_gaps)
        verdict = f"NEEDS SECOND WAVE — 0 missing players; {n} season gaps (review fetch_gaps.csv)"
    elif low_gaps:
        verdict = "REVIEW — low game counts flagged (see fetch_gaps.csv)"
    else:
        verdict = "CLEAN"
    logger.info("VERDICT: %s", verdict)
    logger.info("=" * 70)


def main() -> int:
    """Audit fetched game logs against the population cohort for gaps and quality issues."""
    parquet_path = DATA_DIR / "game_logs.parquet"
    cohort_path = DATA_DIR / "population_cohort.csv"

    if not parquet_path.exists():
        logger.error("%s not found — run fetch_bref_data.py first.", parquet_path)
        sys.exit(1)

    if not cohort_path.exists():
        logger.error("%s not found — run fetch_bref_data.py first.", cohort_path)
        sys.exit(1)

    logs = pd.read_parquet(parquet_path)
    cohort = pd.read_csv(cohort_path)
    names = cohort.set_index("player_id")["player_name"]
    fetched_ids = set(logs["player_id"].unique())

    logger.info("=" * 70)
    logger.info("BASKETBALL-REFERENCE FETCH AUDIT")
    logger.info("=" * 70)
    logger.info("Game log rows:     %s", f"{len(logs):,}")
    logger.info("Cohort players:    %s", f"{len(cohort):,}")
    logger.info("Fetched players:   %s", f"{len(fetched_ids):,}")

    missing_gaps = _audit_missing_players(cohort, fetched_ids, names)
    missing_players = [g[0] for g in missing_gaps]
    season_gaps = _audit_missing_seasons(cohort, logs, missing_players, names)
    low_gaps = _audit_low_game_counts(logs, names)
    _audit_null_rates(logs)
    _log_verdict(missing_players, season_gaps, low_gaps)

    all_gaps = missing_gaps + season_gaps + low_gaps
    gaps_df = pd.DataFrame(all_gaps, columns=["player_id", "player_name", "season", "gap_type"])
    out_path = DATA_DIR / "fetch_gaps.csv"
    gaps_df.to_csv(out_path, index=False)
    logger.info("\nWrote %d gap rows to %s", len(gaps_df), out_path)

    return 1 if (missing_gaps or season_gaps) else 0


if __name__ == "__main__":
    sys.exit(main())
