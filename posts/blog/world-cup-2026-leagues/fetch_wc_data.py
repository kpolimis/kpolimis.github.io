#!/usr/bin/env python3
"""Fetch 2026 FIFA World Cup player stats via soccerdata (uses cached FBref data).

Outputs (written to data/):
  wc_players.csv  — one row per player: name, club, league, nation, minutes, goals, assists
  wc_rounds.csv   — one row per national team: nation, round_reached, round_num

Run aggregate_wc_data.py afterwards to build wc_leagues.csv and wc_epl_clubs.csv.

Prerequisites:
  pip install soccerdata   (uses undetected Chrome to bypass FBref bot protection)

First run opens a Chrome window and may show a CAPTCHA — solve it manually.
Subsequent runs use the soccerdata cache (~/.soccerdata/data/FBref/) and need no browser.

Usage:
  cd posts/blog/world-cup-2026-leagues
  python fetch_wc_data.py          # uses cache
  python fetch_wc_data.py --refresh  # clears cache and re-fetches
"""
from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)

# ── footy (club registry + league normalizer) ──────────────────────────────────
# Prefer the installed package; fall back to the local editable checkout.
FOOTY_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "../../../../football/footy")
)
if os.path.isdir(FOOTY_ROOT) and FOOTY_ROOT not in sys.path:
    sys.path.insert(0, FOOTY_ROOT)
try:
    import footy
    HAS_FOOTY = True
except ImportError:
    HAS_FOOTY = False
    logger.warning("footy not found. Club→league mapping will be degraded.")

# ── Output directory ──────────────────────────────────────────────────────────
DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

# ── Tournament round ordering ─────────────────────────────────────────────────
# 2026 WC used a new 48-team format: 12 groups of 4, then Round of 32.
ROUND_ORDER: dict[str, int] = {
    "Group stage":      1,
    "Round of 32":      2,
    "Round of 16":      3,
    "Quarter-finals":   4,
    "Semi-finals":      5,
    "Third-place match":5,
    "Final":            6,
}
ROUND_LABEL: dict[int, str] = {
    1: "Group Stage",
    2: "Round of 32",
    3: "Round of 16",
    4: "Quarter-finals",
    5: "Semi-finals",
    6: "Final",
}


# ── Club → league mapping via footy ───────────────────────────────────────────

def _strip_rank_prefix(raw: str) -> str:
    """Soccerdata prefixes club names with 'N. ' (e.g. '1. Arsenal'). Strip it."""
    return re.sub(r"^\d+\.\s*", "", str(raw)).strip()


def club_to_league(raw_club: str) -> str:
    """Map a raw club name to a canonical league ID.

    Args:
        raw_club: Raw club name from soccerdata (e.g. '1. Arsenal', '1. Feyenoord').

    Returns:
        League ID string (e.g. 'EPL', 'Eredivisie'), or 'Other' if unmapped.
    """
    if not HAS_FOOTY:
        return "Other"
    clean = _strip_rank_prefix(raw_club)
    try:
        club_id = footy.normalise(clean)
        return footy.get(club_id).league
    except KeyError:
        return "Other"


# ── Fetch player stats ────────────────────────────────────────────────────────

def fetch_player_stats(no_cache: bool = False) -> pd.DataFrame:
    """Fetch per-player standard stats for the 2026 World Cup via FBref.

    Args:
        no_cache: If True, bypass soccerdata cache and re-fetch from FBref.

    Returns:
        DataFrame with one row per player: player, nation, club, league,
        minutes, goals, assists, and supporting columns.
    """
    import soccerdata as sd  # import here so script is importable without it

    fbref = sd.FBref(leagues="INT-World Cup", seasons=2026, no_cache=no_cache)
    raw = fbref.read_player_season_stats(stat_type="standard")

    # Reset index first so (league, season, team, player) become columns with tuple headers
    raw = raw.reset_index()
    if raw.empty:
        raise ValueError(
            "fetch_player_stats: FBref returned 0 players — check cache or re-fetch with --refresh"
        )

    # Flatten multi-level tuple column index: join non-empty parts with '_'
    raw.columns = [
        "_".join(str(p) for p in col if p and "Unnamed" not in str(p)).strip("_")
        for col in raw.columns
    ]

    # Rename to stable names (using the flattened tuple-join names)
    col_map = {
        "player":           "player",
        "team":             "nation",       # national team
        "Club":             "club_raw",
        "nation":           "nation_code",
        "pos":              "position",
        "age":              "age",
        "Playing Time_Min": "minutes",
        "Playing Time_MP":  "matches",
        "Playing Time_Starts": "starts",
        "Performance_Gls":  "goals",
        "Performance_Ast":  "assists",
        "Performance_G+A":  "ga",
    }
    raw = raw.rename(columns={k: v for k, v in col_map.items() if k in raw.columns})

    # Derive clean club name and league
    raw["club"]   = raw["club_raw"].apply(_strip_rank_prefix)
    raw["league"] = raw["club_raw"].apply(club_to_league)

    # Keep only columns we need
    want = ["player", "nation", "nation_code", "position", "club_raw", "club",
            "league", "age", "matches", "starts", "minutes", "goals", "assists", "ga"]
    df = raw[[c for c in want if c in raw.columns]].copy()

    # Convert numeric columns
    for col in ["minutes", "goals", "assists", "ga", "matches", "starts"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    logger.info("%d players loaded; %d distinct leagues", len(df), df["league"].nunique())
    logger.info("%.1f%% of players mapped to a known league",
                (df["league"] != "Other").mean() * 100)
    return df


# ── Fetch tournament round results ────────────────────────────────────────────

def fetch_team_rounds(no_cache: bool = False) -> pd.DataFrame:
    """Derive the furthest tournament round reached by each national team.

    Args:
        no_cache: If True, bypass soccerdata cache and re-fetch from FBref.

    Returns:
        DataFrame with one row per nation: nation, round_num, round_reached.
    """
    import soccerdata as sd

    fbref   = sd.FBref(leagues="INT-World Cup", seasons=2026, no_cache=no_cache)
    sched   = fbref.read_schedule().reset_index()

    sched["_rnd_num"] = (
        sched["round"].astype(str).str.strip().map(ROUND_ORDER).fillna(0).astype(int)
    )
    valid = sched.loc[sched["_rnd_num"] > 0, ["home_team", "away_team", "_rnd_num"]]
    long = pd.concat(
        [
            valid.rename(columns={"home_team": "nation"})[["nation", "_rnd_num"]],
            valid.rename(columns={"away_team": "nation"})[["nation", "_rnd_num"]],
        ],
        ignore_index=True,
    )
    long = long.loc[
        long["nation"].astype(str).str.lower().ne("nan") & long["nation"].astype(str).ne("")
    ]
    team_max: dict[str, int] = long.groupby("nation")["_rnd_num"].max().to_dict()

    if not team_max:
        raise ValueError(
            "fetch_team_rounds: no nations resolved from schedule — check ROUND_ORDER mapping"
        )
    records = [
        {
            "nation":         team,
            "round_num":      rnd_num,
            "round_reached":  ROUND_LABEL.get(rnd_num, "Group Stage"),
        }
        for team, rnd_num in team_max.items()
    ]
    df = pd.DataFrame(records).sort_values("round_num", ascending=False)
    logger.info("%d nations tracked; deepest round: %s",
                len(df), df["round_reached"].iloc[0])
    return df


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    """Entry point: fetch and save raw per-player and per-nation 2026 WC data."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )

    parser = argparse.ArgumentParser(description="Fetch 2026 WC data via soccerdata")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-fetch from FBref (opens Chrome, may show CAPTCHA)")
    args = parser.parse_args()
    no_cache = args.refresh

    logger.info("Fetching player stats...")
    players = fetch_player_stats(no_cache=no_cache)

    logger.info("Fetching team round results...")
    rounds = fetch_team_rounds(no_cache=no_cache)

    players.to_csv(f"{DATA_DIR}/wc_players.csv", index=False)
    rounds.to_csv(f"{DATA_DIR}/wc_rounds.csv",   index=False)

    logger.info("Saved:")
    logger.info("  %s/wc_players.csv   (%d rows)", DATA_DIR, len(players))
    logger.info("  %s/wc_rounds.csv    (%d rows)", DATA_DIR, len(rounds))
    logger.info("Run aggregate_wc_data.py to build wc_leagues.csv and wc_epl_clubs.csv")


if __name__ == "__main__":
    main()
