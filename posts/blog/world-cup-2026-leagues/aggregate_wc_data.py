#!/usr/bin/env python3
"""Aggregate 2026 FIFA World Cup raw CSVs into league- and club-level summaries.

Reads the outputs of fetch_wc_data.py and produces:
  wc_leagues.csv  — aggregated by club league: total_minutes, goals, assists, G+A per 90
  wc_epl_clubs.csv — aggregated by EPL club: wc_minutes, goals, assists, G+A per 90

Run fetch_wc_data.py first to populate wc_players.csv.

Usage:
  cd posts/blog/world-cup-2026-leagues
  python aggregate_wc_data.py              # reads data/wc_players.csv by default
  python aggregate_wc_data.py --data-dir /path/to/data
"""
from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

DATA_DIR = "data"


# ── League aggregation ────────────────────────────────────────────────────────

def build_league_stats(players: pd.DataFrame) -> pd.DataFrame:
    """Aggregate player stats to the league level.

    Args:
        players: Output of fetch_wc_data.fetch_player_stats(), with a 'league' column.

    Returns:
        DataFrame with one row per league: total_minutes, goals, assists,
        player_count, ga_per90, goals_per90.
    """
    agg = (
        players
        .groupby("league", dropna=False)
        .agg(
            total_minutes= ("minutes",  "sum"),
            total_goals=   ("goals",    "sum"),
            total_assists= ("assists",  "sum"),
            player_count=  ("player",   "count"),
        )
        .reset_index()
        .sort_values("total_minutes", ascending=False)
    )
    nineties = agg["total_minutes"].div(90).replace(0, np.nan)
    agg["ga_per90"]    = ((agg["total_goals"] + agg["total_assists"]) / nineties).round(3)
    agg["goals_per90"] = (agg["total_goals"] / nineties).round(3)
    return agg


# ── EPL club aggregation ──────────────────────────────────────────────────────

def build_epl_club_stats(players: pd.DataFrame) -> pd.DataFrame:
    """Aggregate EPL player stats to the club level.

    Args:
        players: Output of fetch_wc_data.fetch_player_stats(), with 'league' and 'club' columns.

    Returns:
        DataFrame with one row per EPL club: wc_minutes, goals, assists,
        player_count, ga_per90.
    """
    epl = players[players["league"] == "EPL"].copy()
    if epl.empty:
        logger.warning(
            "build_epl_club_stats: no EPL players found — "
            "check footy club-to-league mapping or input data"
        )
        return pd.DataFrame(
            columns=["club", "wc_minutes", "wc_goals", "wc_assists", "player_count", "ga_per90"]
        )
    agg = (
        epl
        .groupby("club", dropna=False)
        .agg(
            wc_minutes=   ("minutes",  "sum"),
            wc_goals=     ("goals",    "sum"),
            wc_assists=   ("assists",  "sum"),
            player_count= ("player",   "count"),
        )
        .reset_index()
        .sort_values("wc_minutes", ascending=False)
    )
    nineties        = agg["wc_minutes"].div(90).replace(0, np.nan)
    agg["ga_per90"] = ((agg["wc_goals"] + agg["wc_assists"]) / nineties).round(3)
    return agg


# ── Unknown clubs report ──────────────────────────────────────────────────────

def report_unmapped(players: pd.DataFrame, top_n: int = 30) -> None:
    """Log the clubs whose league could not be resolved via footy.

    Args:
        players: DataFrame with a 'league' column (value 'Other' = unmapped).
        top_n: Number of unmapped clubs to log, ordered by total minutes.
    """
    unmapped = (
        players[players["league"] == "Other"]
        .groupby("club", dropna=False)
        .agg(minutes=("minutes", "sum"), players=("player", "count"))
        .sort_values("minutes", ascending=False)
        .head(top_n)
    )
    if unmapped.empty:
        logger.info("All clubs mapped.")
        return
    total_unmapped = players[players["league"] == "Other"]["minutes"].sum()
    total          = players["minutes"].sum()
    if total:
        logger.warning("Unmapped minutes: %s of %s (%.1f%%)",
                       f"{total_unmapped:,.0f}", f"{total:,.0f}",
                       total_unmapped / total * 100)
    else:
        logger.warning("Unmapped minutes: %s of 0 (0.0%%)", f"{total_unmapped:,.0f}")
    logger.info("Top unmapped clubs by minutes:\n%s", unmapped.to_string())
    logger.info("To improve coverage, add these clubs to footy/clubs.py.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    """Entry point: read raw CSVs, build summaries, and save."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Aggregate raw WC CSVs into league and club summaries"
    )
    parser.add_argument(
        "--data-dir", default=DATA_DIR,
        help="Directory containing wc_players.csv (default: %(default)s)",
    )
    args = parser.parse_args()
    data_dir = args.data_dir

    players_path = f"{data_dir}/wc_players.csv"
    logger.info("Reading %s", players_path)
    players = pd.read_csv(players_path)
    if players.empty:
        raise ValueError(
            f"Zero rows in {players_path} — run fetch_wc_data.py first to populate it"
        )

    for col in ["minutes", "goals", "assists"]:
        if col in players.columns:
            players[col] = pd.to_numeric(players[col], errors="coerce")
    for col in ["minutes", "goals", "assists"]:
        n_nan = players[col].isna().sum()
        if n_nan:
            logger.warning("  %s: %d non-numeric values coerced to NaN", col, n_nan)

    logger.info("Building league aggregates...")
    leagues   = build_league_stats(players)
    logger.info("Building EPL club aggregates...")
    epl_clubs = build_epl_club_stats(players)

    logger.info("Unmapped clubs:")
    report_unmapped(players)

    leagues.to_csv(f"{data_dir}/wc_leagues.csv",      index=False)
    epl_clubs.to_csv(f"{data_dir}/wc_epl_clubs.csv",  index=False)

    logger.info("Saved:")
    logger.info("  %s/wc_leagues.csv   (%d rows)", data_dir, len(leagues))
    logger.info("  %s/wc_epl_clubs.csv (%d rows)", data_dir, len(epl_clubs))
    logger.info("Top 12 leagues by minutes:\n%s",
                leagues[["league", "total_minutes", "ga_per90", "player_count"]]
                .head(12).to_string(index=False))


if __name__ == "__main__":
    main()
