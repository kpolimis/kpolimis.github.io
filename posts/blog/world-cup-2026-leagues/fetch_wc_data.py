#!/usr/bin/env python3
"""
Fetch 2026 FIFA World Cup player stats via soccerdata (uses cached FBref data).

Outputs (written to data/):
  wc_players.csv  — one row per player: name, club, league, nation, minutes, goals, assists
  wc_rounds.csv   — one row per national team: nation, round_reached, round_num
  wc_leagues.csv  — aggregated by club league: total_minutes, goals, assists, G+A per 90

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
import os
import re
import sys
import warnings

import pandas as pd

warnings.filterwarnings("ignore")

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
    print("WARNING: footy not found. Club→league mapping will be degraded.")

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
    """soccerdata prefixes club names with 'N. ' (e.g. '1. Arsenal'). Strip it."""
    return re.sub(r"^\d+\.\s*", "", str(raw)).strip()


def club_to_league(raw_club: str) -> str:
    """
    Map a raw club name (e.g. '1. Arsenal', '1. Feyenoord') to a canonical
    league ID (e.g. 'EPL', 'Eredivisie').

    Uses footy.normalise() → club.league. Falls back to 'Other' for clubs
    not yet in the footy registry; add them to footy/clubs.py to improve coverage.
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
    import soccerdata as sd  # import here so script is importable without it

    fbref = sd.FBref(leagues="INT-World Cup", seasons=2026, no_cache=no_cache)
    raw = fbref.read_player_season_stats(stat_type="standard")

    # Reset index first so (league, season, team, player) become columns with tuple headers
    raw = raw.reset_index()

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

    print(f"  {len(df)} players loaded; {df['league'].nunique()} distinct leagues")
    print(f"  coverage: {(df['league'] != 'Other').mean():.1%} of players mapped to a known league")
    return df


# ── Fetch tournament round results ────────────────────────────────────────────

def fetch_team_rounds(no_cache: bool = False) -> pd.DataFrame:
    import soccerdata as sd

    fbref   = sd.FBref(leagues="INT-World Cup", seasons=2026, no_cache=no_cache)
    sched   = fbref.read_schedule().reset_index()

    team_max: dict[str, int] = {}
    for _, row in sched.iterrows():
        rnd       = str(row.get("round", "")).strip()
        home      = str(row.get("home_team", "")).strip()
        away      = str(row.get("away_team", "")).strip()
        rnd_num   = ROUND_ORDER.get(rnd, 0)
        if rnd_num == 0:
            continue
        for team in [home, away]:
            if team and team.lower() != "nan":
                team_max[team] = max(team_max.get(team, 0), rnd_num)

    records = [
        {
            "nation":         team,
            "round_num":      rnd_num,
            "round_reached":  ROUND_LABEL.get(rnd_num, "Group Stage"),
        }
        for team, rnd_num in team_max.items()
    ]
    df = pd.DataFrame(records).sort_values("round_num", ascending=False)
    print(f"  {len(df)} nations tracked; deepest round: {df['round_reached'].iloc[0]}")
    return df


# ── League aggregation ────────────────────────────────────────────────────────

def build_league_stats(players: pd.DataFrame) -> pd.DataFrame:
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
    nineties = agg["total_minutes"] / 90
    agg["ga_per90"]     = ((agg["total_goals"] + agg["total_assists"]) / nineties).round(3)
    agg["goals_per90"]  = (agg["total_goals"] / nineties).round(3)
    return agg


# ── EPL club aggregation ──────────────────────────────────────────────────────

def build_epl_club_stats(players: pd.DataFrame) -> pd.DataFrame:
    epl = players[players["league"] == "EPL"].copy()
    agg = (
        epl
        .groupby("club")
        .agg(
            wc_minutes=  ("minutes",  "sum"),
            wc_goals=    ("goals",    "sum"),
            wc_assists=  ("assists",  "sum"),
            player_count=("player",   "count"),
        )
        .reset_index()
        .sort_values("wc_minutes", ascending=False)
    )
    nineties         = agg["wc_minutes"] / 90
    agg["ga_per90"]  = ((agg["wc_goals"] + agg["wc_assists"]) / nineties).round(3)
    return agg


# ── Unknown clubs report ───────────────────────────────────────────────────────

def report_unmapped(players: pd.DataFrame, top_n: int = 30) -> None:
    unmapped = (
        players[players["league"] == "Other"]
        .groupby("club")
        .agg(minutes=("minutes", "sum"), players=("player", "count"))
        .sort_values("minutes", ascending=False)
        .head(top_n)
    )
    if unmapped.empty:
        print("  All clubs mapped.")
        return
    total_unmapped = players[players["league"] == "Other"]["minutes"].sum()
    total          = players["minutes"].sum()
    print(f"  Unmapped minutes: {total_unmapped:,.0f} of {total:,.0f} "
          f"({total_unmapped / total:.1%})")
    print(f"  Top unmapped clubs by minutes:")
    print(unmapped.to_string())
    print()
    print("  To improve coverage, add these clubs to footy/clubs.py.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch 2026 WC data via soccerdata")
    parser.add_argument("--refresh", action="store_true",
                        help="Re-fetch from FBref (opens Chrome, may show CAPTCHA)")
    args = parser.parse_args()
    no_cache = args.refresh

    print("Fetching player stats...")
    players = fetch_player_stats(no_cache=no_cache)

    print("Fetching team round results...")
    rounds = fetch_team_rounds(no_cache=no_cache)

    print("Building aggregates...")
    leagues   = build_league_stats(players)
    epl_clubs = build_epl_club_stats(players)

    print("\nUnmapped clubs (add to footy to improve league coverage):")
    report_unmapped(players)

    players.to_csv(f"{DATA_DIR}/wc_players.csv",   index=False)
    rounds.to_csv(f"{DATA_DIR}/wc_rounds.csv",     index=False)
    leagues.to_csv(f"{DATA_DIR}/wc_leagues.csv",   index=False)
    epl_clubs.to_csv(f"{DATA_DIR}/wc_epl_clubs.csv", index=False)

    print(f"\nSaved:")
    print(f"  {DATA_DIR}/wc_players.csv   ({len(players)} rows)")
    print(f"  {DATA_DIR}/wc_rounds.csv    ({len(rounds)} rows)")
    print(f"  {DATA_DIR}/wc_leagues.csv   ({len(leagues)} rows)")
    print(f"  {DATA_DIR}/wc_epl_clubs.csv ({len(epl_clubs)} rows)")
    print()
    print("Top 12 leagues by minutes:")
    print(
        leagues[["league", "total_minutes", "ga_per90", "player_count"]]
        .head(12)
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()
