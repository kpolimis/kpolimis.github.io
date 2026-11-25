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

# Season-length awareness (issue #76): shortened seasons, by season-ending year.
# 2020 (COVID) teams played 63-75 games; use the minimum to avoid false alarms.
SEASON_LENGTHS = {1999: 50, 2012: 66, 2020: 63, 2021: 72}
FULL_SEASON_LENGTH = 82
PARTIAL_SEASON_FRACTION = 0.5  # flag seasons with < 50% of expected games fetched

# Documented career gaps (issue #75): retirements / overseas stints that are NOT
# fetch errors. Typed `career_gap` in fetch_gaps.csv; excluded from verdict/exit.
KNOWN_CAREER_GAPS: dict[str, set[int]] = {
    "jordami01": {1994, 1999, 2000, 2001},  # Michael Jordan: two retirements
}

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


def _audit_unexpected_players(cohort: pd.DataFrame, fetched_ids: set, logs: pd.DataFrame) -> list:
    """Report players present in game_logs but absent from the cohort CSV (issue #77).

    Catches silent drift when the cohort CSV is regenerated smaller or a wrong
    player was fetched. Included in verdict/exit code when non-empty.
    """
    unexpected = sorted(fetched_ids - set(cohort["player_id"]))
    logger.info("\n--- Players fetched but NOT in cohort CSV: %d ---", len(unexpected))
    if not unexpected:
        return []
    fetched_names = logs.drop_duplicates("player_id").set_index("player_id")["player_name"]
    logger.warning("Cohort drift: fetched players missing from population_cohort.csv")
    _log_capped([f"  {pid:<12} {fetched_names.get(pid, '?')}" for pid in unexpected])
    return [(pid, fetched_names.get(pid, ""), "", "unexpected_player") for pid in unexpected]


def _audit_duplicates(logs: pd.DataFrame, names: pd.Series) -> int:
    """Report duplicate (player_id, Date) rows (issue #74); return the duplicate count.

    Duplicates inflate game counts, corrupt games_missed_per_82 and B2B flags,
    and propagate to quarter_splits via the rest_days merge. Included in
    verdict/exit code when non-zero.
    """
    dup_mask = logs.duplicated(subset=["player_id", "Date"], keep="first")
    n_dups = int(dup_mask.sum())
    logger.info("\n--- Duplicate (player_id, Date) rows: %d ---", n_dups)
    if n_dups:
        dups = logs.loc[dup_mask, ["player_id", "Date", "season"]]
        logger.warning("Duplicates found — dedupe parquet (fetch_bref_data.save now dedupes)")
        _log_capped(
            [
                f"  {r.player_id:<12} {names.get(r.player_id, '?'):<28} {r.Date}"
                for r in dups.itertuples()
            ]
        )
    return n_dups


def _audit_missing_seasons(
    cohort: pd.DataFrame, logs: pd.DataFrame, missing_players: list, names: pd.Series
) -> list:
    """Report season gaps for fetched players; return gap rows."""
    # cohort debut/final years use the same season-ending-year convention as
    # the parquet's `season` column (e.g. 1984-85 season -> 1985)
    seasons_by_player = logs.groupby("player_id")["season"].agg(set)
    missing_player_set = set(missing_players)
    missing_season_rows = []
    gaps = []
    n_known_gaps = 0
    for row in cohort.itertuples():
        if row.player_id in missing_player_set:
            continue
        expected = set(range(row.debut_year, row.final_year + 1))
        have = seasons_by_player.get(row.player_id, set())
        # Documented career gaps (issue #75) are typed `career_gap`, not
        # `missing_season`, so they never trigger a refetch wave or exit 1.
        known = KNOWN_CAREER_GAPS.get(row.player_id, set())
        documented = sorted((expected - have) & known)
        n_known_gaps += len(documented)
        gaps.extend((row.player_id, row.player_name, s, "career_gap") for s in documented)
        missing = sorted(expected - have - known)
        if missing:
            missing_season_rows.append((row.player_id, row.player_name, missing))
            gaps.extend((row.player_id, row.player_name, s, "missing_season") for s in missing)
    logger.info("\n--- Players with missing seasons: %d ---", len(missing_season_rows))
    logger.info("(note: a missing mid-career season can be legitimate, e.g. overseas)")
    if n_known_gaps:
        logger.info(
            "(%d documented career-gap seasons excluded — see KNOWN_CAREER_GAPS)", n_known_gaps
        )
    _log_capped([f"  {pid:<12} {name:<28} missing: {ms}" for pid, name, ms in missing_season_rows])
    return gaps


def _audit_low_game_counts(logs: pd.DataFrame, names: pd.Series) -> list:
    """Report (player, season) pairs with suspiciously few games; return gap rows.

    Season-length-aware (issue #76): a season is flagged when the fetched game
    count is below PARTIAL_SEASON_FRACTION of that season's schedule length, so
    a VPN-interrupted 25-of-82 fetch no longer passes silently. Shortened
    seasons (1999=50, 2012=66, 2020~63, 2021=72) use their real lengths to
    avoid false alarms. Counts dedupe on (player_id, Date) first so duplicate
    rows (issue #74) cannot mask a genuinely low count.
    """
    game_counts = (
        logs.drop_duplicates(subset=["player_id", "Date"])
        .groupby(["player_id", "season"])
        .size()
        .sort_index()
    )
    gaps = []
    lines = []
    for (pid, season), n in game_counts.items():
        expected = SEASON_LENGTHS.get(int(season), FULL_SEASON_LENGTH)
        if n >= expected * PARTIAL_SEASON_FRACTION:
            continue
        gap_type = "low_game_count" if n < LOW_GAME_THRESHOLD else "partial_season"
        gaps.append((pid, names.get(pid, ""), season, gap_type))
        lines.append(f"  {pid:<12} {names.get(pid, '?'):<28} {season}  ({n}/{expected} games)")
    logger.info(
        "\n--- (player, season) pairs with <%d%% of season length: %d ---",
        int(PARTIAL_SEASON_FRACTION * 100),
        len(gaps),
    )
    logger.info("(flagged for review, not treated as fetch errors)")
    _log_capped(lines)
    return gaps


def _audit_null_rates(logs: pd.DataFrame) -> None:
    """Log NULL rates for key columns."""
    logger.info("\n--- NULL rates (key columns) ---")
    for col in KEY_COLUMNS:
        if col not in logs.columns:
            logger.warning("  %s  MISSING FROM PARQUET", col)
            continue
        rate = logs[col].isna().mean()
        logger.info("  %-12s %7.2f%%  (%s nulls)", col, rate * 100, f"{logs[col].isna().sum():,}")


def _log_verdict(
    missing_players: list,
    missing_season_gaps: list,
    low_gaps: list,
    n_duplicates: int = 0,
    unexpected_players: list | None = None,
) -> None:
    """Log the summary verdict line."""
    unexpected_players = unexpected_players or []
    logger.info("\n%s", "=" * 70)
    if missing_players:
        verdict = f"NEEDS SECOND WAVE — {len(missing_players)} players completely missing"
    elif missing_season_gaps:
        n = len(missing_season_gaps)
        verdict = f"NEEDS SECOND WAVE — 0 missing players; {n} season gaps (review fetch_gaps.csv)"
    elif n_duplicates:
        verdict = f"FAIL — {n_duplicates} duplicate (player_id, Date) rows (dedupe parquet)"
    elif unexpected_players:
        n = len(unexpected_players)
        verdict = f"FAIL — {n} fetched players not in cohort CSV (cohort drift)"
    elif low_gaps:
        verdict = "REVIEW — low/partial game counts flagged (see fetch_gaps.csv)"
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

    # Guard against duplicate player_id in the cohort CSV (issue #78):
    # set_index would raise ValueError, or worse, names.get() would return a
    # Series and crash the f-string formatting mid-run.
    n_before = len(cohort)
    cohort = cohort.drop_duplicates(subset="player_id", keep="first")
    n_cohort_dupes = n_before - len(cohort)
    if n_cohort_dupes:
        logger.warning(
            "Dropped %d duplicate player_id row(s) from %s", n_cohort_dupes, cohort_path.name
        )

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
    unexpected_gaps = _audit_unexpected_players(cohort, fetched_ids, logs)
    season_gaps = _audit_missing_seasons(cohort, logs, missing_players, names)
    # Documented career gaps (`career_gap`) are informational — only true
    # `missing_season` rows should trigger a second fetch wave (issue #75).
    hard_season_gaps = [g for g in season_gaps if g[3] == "missing_season"]
    n_duplicates = _audit_duplicates(logs, names)
    low_gaps = _audit_low_game_counts(logs, names)
    _audit_null_rates(logs)
    _log_verdict(missing_players, hard_season_gaps, low_gaps, n_duplicates, unexpected_gaps)

    all_gaps = missing_gaps + unexpected_gaps + season_gaps + low_gaps
    gaps_df = pd.DataFrame(all_gaps, columns=["player_id", "player_name", "season", "gap_type"])
    out_path = DATA_DIR / "fetch_gaps.csv"
    gaps_df.to_csv(out_path, index=False)
    logger.info("\nWrote %d gap rows to %s", len(gaps_df), out_path)

    return 1 if (missing_gaps or hard_season_gaps or n_duplicates or unexpected_gaps) else 0


if __name__ == "__main__":
    sys.exit(main())
