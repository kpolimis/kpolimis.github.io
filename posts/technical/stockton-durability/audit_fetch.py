"""Audit Basketball-Reference population fetch against the expected cohort.

Usage: python audit_fetch.py
Writes data/fetch_gaps.csv for a targeted second fetch wave.
"""

import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
LOW_GAME_THRESHOLD = 20
MAX_PRINT = 25  # console cap per section; full detail goes to fetch_gaps.csv
KEY_COLUMNS = ["Date", "MP", "mp_float", "PTS", "player_id", "season", "player_name"]


def print_capped(lines):
    """Print up to MAX_PRINT lines, then summarize the remainder."""
    for line in lines[:MAX_PRINT]:
        print(line)
    if len(lines) > MAX_PRINT:
        print(f"  ... and {len(lines) - MAX_PRINT} more (see fetch_gaps.csv)")


def _audit_missing_players(cohort: pd.DataFrame, fetched_ids: set, names: pd.Series) -> list:
    """Report players missing entirely from the fetch; return gap rows."""
    missing = sorted(set(cohort["player_id"]) - fetched_ids)
    print(f"\n--- Players completely missing: {len(missing)} ---")
    print_capped([f"  {pid:<12} {names.get(pid, '?')}" for pid in missing])
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
    print(f"\n--- Players with missing seasons: {len(missing_season_rows)} ---")
    print("(note: a missing mid-career season can be legitimate, e.g. overseas)")
    print_capped([f"  {pid:<12} {name:<28} missing: {ms}" for pid, name, ms in missing_season_rows])
    return gaps


def _audit_low_game_counts(logs: pd.DataFrame, names: pd.Series) -> list:
    """Report (player, season) pairs with suspiciously few games; return gap rows."""
    game_counts = logs.groupby(["player_id", "season"]).size()
    low = game_counts[game_counts < LOW_GAME_THRESHOLD].sort_index()
    print(f"\n--- (player, season) pairs with <{LOW_GAME_THRESHOLD} games: {len(low)} ---")
    print("(flagged for review, not treated as fetch errors)")
    print_capped(
        [
            f"  {pid:<12} {names.get(pid, '?'):<28} {season}  ({n} games)"
            for (pid, season), n in low.items()
        ]
    )
    return [
        (pid, names.get(pid, ""), season, "low_game_count") for (pid, season), _n in low.items()
    ]


def _audit_null_rates(logs: pd.DataFrame) -> None:
    """Print NULL rates for key columns."""
    print("\n--- NULL rates (key columns) ---")
    for col in KEY_COLUMNS:
        if col not in logs.columns:
            print(f"  {col:<12} MISSING FROM PARQUET")
            continue
        rate = logs[col].isna().mean()
        print(f"  {col:<12} {rate:>8.2%}  ({logs[col].isna().sum():,} nulls)")


def _print_verdict(missing_players: list, missing_season_gaps: list, low_gaps: list) -> None:
    """Print the summary verdict line."""
    print("\n" + "=" * 70)
    if missing_players:
        verdict = f"NEEDS SECOND WAVE — {len(missing_players)} players completely missing"
    elif missing_season_gaps:
        n = len(missing_season_gaps)
        verdict = f"FETCH COMPLETE — 0 missing players; {n} season gaps (review fetch_gaps.csv)"
    elif low_gaps:
        verdict = "CLEAN — low game counts flagged for review"
    else:
        verdict = "CLEAN"
    print(f"VERDICT: {verdict}")
    print("=" * 70)


def main():
    """Audit fetched game logs against the population cohort for gaps and quality issues."""
    parquet_path = DATA_DIR / "game_logs.parquet"
    cohort_path = DATA_DIR / "population_cohort.csv"

    if not parquet_path.exists():
        print(f"ERROR: {parquet_path} not found. Run the fetch first.")
        sys.exit(1)

    logs = pd.read_parquet(parquet_path)
    cohort = pd.read_csv(cohort_path)
    names = cohort.set_index("player_id")["player_name"]
    fetched_ids = set(logs["player_id"].unique())

    print("=" * 70)
    print("BASKETBALL-REFERENCE FETCH AUDIT")
    print("=" * 70)
    print(f"Game log rows:     {len(logs):,}")
    print(f"Cohort players:    {len(cohort):,}")
    print(f"Fetched players:   {len(fetched_ids):,}")

    missing_gaps = _audit_missing_players(cohort, fetched_ids, names)
    missing_players = [g[0] for g in missing_gaps]
    season_gaps = _audit_missing_seasons(cohort, logs, missing_players, names)
    low_gaps = _audit_low_game_counts(logs, names)
    _audit_null_rates(logs)
    _print_verdict(missing_players, season_gaps, low_gaps)

    all_gaps = missing_gaps + season_gaps + low_gaps
    gaps_df = pd.DataFrame(all_gaps, columns=["player_id", "player_name", "season", "gap_type"])
    out_path = DATA_DIR / "fetch_gaps.csv"
    gaps_df.to_csv(out_path, index=False)
    print(f"\nWrote {len(gaps_df):,} gap rows to {out_path}")


if __name__ == "__main__":
    main()
