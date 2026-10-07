"""Stage 1 data build for the Week-1 overreaction study.

Downloads and freezes 18 EPL seasons (2008/09-2025/26) of football-data.co.uk
match data via ``footy_stats``, then builds a one-row-per-team-season panel
with the Week-1 signal (``week1_shock``), regime indicators, and full-season
outcomes. No fitted model is used anywhere in this stage: ``prior_strength``,
``preseason_tier``, and ``week1_opponent_tier`` are deliberately absent (they
belong to the later seed/link stage of the method spec).

Run from the post directory:

    python3 build_panel.py

Outputs (all under ``data/``):
    - ``matches/matches_<season>.parquet`` — one tidy frame per season
    - ``matches_all.parquet`` — all seasons combined, with a ``season`` column
    - ``panel.parquet`` / ``panel.csv`` — the team-season panel
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from footy_stats import cache
from footy_stats.sources.football_data import load_matches
from footy_stats.stats.odds import devig

logger = logging.getLogger(__name__)

SEASONS: list[str] = [
    "0809", "0910", "1011", "1112", "1213", "1314", "1415", "1516", "1617",
    "1718", "1819", "1920", "2021", "2122", "2223", "2324", "2425", "2526",
]

POST_DIR = Path(__file__).resolve().parent
DATA_DIR = POST_DIR / "data"
MATCHES_DIR = DATA_DIR / "matches"

_POINTS = {"W": 3, "D": 1, "L": 0}
_COVID_SEASONS = {"1920", "2021"}


def load_all_seasons(seasons: list[str] = SEASONS) -> pd.DataFrame:
    """Load and freeze every season, returning one combined match frame.

    Each season's tidy frame is frozen to ``data/matches/`` and the combined
    frame (with a ``season`` column holding the 4-digit code string) to
    ``data/matches_all.parquet``.

    Args:
        seasons: football-data 4-digit season codes, e.g. ``"0809"``.

    Returns:
        All matches across ``seasons`` with a leading ``season`` column.
    """
    frames = []
    for season in seasons:
        matches = load_matches(season, "E0", use_cache=True)
        matches.insert(0, "season", season)
        cache.freeze(matches, MATCHES_DIR, f"matches_{season}")
        frames.append(matches)
    combined = pd.concat(frames, ignore_index=True)
    cache.freeze(combined, DATA_DIR, "matches_all")
    return combined


def _team_long(matches: pd.DataFrame) -> pd.DataFrame:
    """Explode a match frame into two team-perspective rows per match.

    Args:
        matches: one season's tidy match frame.

    Returns:
        Frame with one row per (match, team) carrying ``club_id``,
        ``opponent_id``, ``is_home``, goals for/against, and a ``match_idx``
        pointing back to the source row in ``matches``.
    """
    base = matches.reset_index(drop=True).reset_index(names="match_idx")
    home = base.rename(
        columns={
            "home_club_id": "club_id",
            "away_club_id": "opponent_id",
            "fthg": "gf",
            "ftag": "ga",
        }
    )
    home["is_home"] = True
    away = base.rename(
        columns={
            "away_club_id": "club_id",
            "home_club_id": "opponent_id",
            "ftag": "gf",
            "fthg": "ga",
        }
    )
    away["is_home"] = False
    long = pd.concat([home, away], ignore_index=True)
    long["result"] = "D"
    long.loc[long["gf"] > long["ga"], "result"] = "W"
    long.loc[long["gf"] < long["ga"], "result"] = "L"
    long["points"] = long["result"].map(_POINTS)
    return long


def build_season_table(matches: pd.DataFrame) -> pd.DataFrame:
    """Compute the final league table for one season's matches.

    Position ranks by points, then goal difference, then goals for — the
    Premier League's tie-break order (head-to-head beyond that is ignored;
    it has never been needed to separate a top-4 or relegation place in the
    sampled seasons).

    Args:
        matches: one season's tidy match frame.

    Returns:
        One row per club: ``club_id, final_points, final_gd, final_position,
        made_top4, relegated``.
    """
    long = _team_long(matches)
    table = (
        long.groupby("club_id", as_index=False)
        .agg(final_points=("points", "sum"), gf=("gf", "sum"), ga=("ga", "sum"))
        .astype({"final_points": int, "gf": int, "ga": int})
    )
    table["final_gd"] = table["gf"] - table["ga"]
    table = table.sort_values(
        ["final_points", "final_gd", "gf"], ascending=False, kind="mergesort"
    ).reset_index(drop=True)
    table["final_position"] = table.index + 1
    table["made_top4"] = table["final_position"] <= 4
    table["relegated"] = table["final_position"] >= 18
    return table[
        ["club_id", "final_points", "final_gd", "final_position", "made_top4", "relegated"]
    ]


def _week1_odds(row: pd.Series, is_home: bool) -> tuple[float, float, str]:
    """De-vig one match's B365 1X2 and return this team's win/draw probability.

    Prefers closing (``b365c*``) odds, falling back to opening (``b365*``)
    when the closing triple is absent or incomplete, per the method spec's
    graceful-degradation rule.

    Args:
        row: one match row from the tidy frame.
        is_home: whether the team of interest played at home.

    Returns:
        ``(p_win, p_draw, odds_source)`` where ``odds_source`` is ``"b365c"``,
        ``"b365"``, or ``"none"`` (probabilities are NaN for ``"none"``).
    """
    for prefix, label in (("b365c", "b365c"), ("b365", "b365")):
        cols = [f"{prefix}h", f"{prefix}d", f"{prefix}a"]
        if not all(c in row.index for c in cols):
            continue
        odds = [row[c] for c in cols]
        if any(pd.isna(o) for o in odds):
            continue
        p_home, p_draw, p_away = devig([1 / o for o in odds], method="shin")
        return (p_home if is_home else p_away), p_draw, label
    return float("nan"), float("nan"), "none"


def week1_rows(matches: pd.DataFrame) -> pd.DataFrame:
    """Extract each team's Week-1 signal from one season's matches.

    A team's Week-1 match is its chronologically earliest fixture of the
    season (minimum ``date``). ``week1_expected_points`` de-vigs the match's
    B365 1X2 (closing preferred, opening fallback) with Shin's method and
    takes ``3 * p_win + 1 * p_draw``; ``week1_shock`` is actual minus
    expected points.

    Args:
        matches: one season's tidy match frame.

    Returns:
        One row per club: ``club_id, home_week1, week1_opponent_id,
        week1_result, week1_points, week1_expected_points, week1_shock,
        week1_odds_source, week1_match_idx``.
    """
    long = _team_long(matches)
    first = long.loc[long.groupby("club_id")["date"].idxmin()].reset_index(drop=True)
    base = matches.reset_index(drop=True)

    records = []
    for row in first.itertuples(index=False):
        p_win, p_draw, source = _week1_odds(base.iloc[row.match_idx], row.is_home)
        expected = 3 * p_win + 1 * p_draw
        records.append(
            {
                "club_id": row.club_id,
                "home_week1": row.is_home,
                "week1_opponent_id": row.opponent_id,
                "week1_result": row.result,
                "week1_points": int(row.points),
                "week1_expected_points": expected,
                "week1_shock": row.points - expected,
                "week1_odds_source": source,
                "week1_match_idx": int(row.match_idx),
            }
        )
    return pd.DataFrame.from_records(records)


def build_panel(all_matches: pd.DataFrame) -> pd.DataFrame:
    """Build the team-season panel from the combined match frame.

    Args:
        all_matches: output of :func:`load_all_seasons` (must carry a
            ``season`` column of 4-digit code strings).

    Returns:
        One row per team-season with identity, Week-1 signal, regime
        indicators, and full-season outcomes. ``newly_promoted`` is NA for
        the earliest season (no prior season to compare against).
    """
    seasons = sorted(all_matches["season"].unique())
    parts = []
    for season in seasons:
        matches = all_matches.loc[all_matches["season"] == season].reset_index(drop=True)
        part = week1_rows(matches).merge(build_season_table(matches), on="club_id", validate="1:1")
        part.insert(0, "season", season)
        parts.append(part)
    panel = pd.concat(parts, ignore_index=True)

    clubs_by_season = {s: set(p["club_id"]) for s, p in zip(seasons, parts, strict=True)}
    promoted = pd.Series(pd.NA, index=panel.index, dtype="boolean")
    for i, season in enumerate(seasons):
        if i == 0:
            continue  # no prior season observed; promoted status unknown
        mask = panel["season"] == season
        promoted.loc[mask] = ~panel.loc[mask, "club_id"].isin(clubs_by_season[seasons[i - 1]])
    panel["newly_promoted"] = promoted
    panel["post_psr"] = panel["season"] >= "1314"
    panel["psr_enforcement"] = panel["season"] >= "2324"
    panel["covid_restart"] = panel["season"].isin(_COVID_SEASONS)

    return panel[
        [
            "season", "club_id",
            "home_week1", "week1_opponent_id", "week1_result", "week1_points",
            "week1_expected_points", "week1_shock", "week1_odds_source",
            "newly_promoted", "post_psr", "psr_enforcement", "covid_restart",
            "final_points", "final_gd", "final_position", "made_top4", "relegated",
        ]
    ]


def _check(condition: bool, message: str) -> None:
    """Raise ``AssertionError`` with ``message`` unless ``condition`` holds."""
    if not condition:
        raise AssertionError(message)


def validate(panel: pd.DataFrame, all_matches: pd.DataFrame) -> None:
    """Run loud sanity checks on the panel and match data.

    Args:
        panel: output of :func:`build_panel`.
        all_matches: the combined match frame the panel was built from.

    Raises:
        AssertionError: on any structural violation (club counts, match
        counts, top-4/relegation quotas, W1 match resolution, missing shocks).
    """
    season_sizes = all_matches.groupby("season").size()
    club_counts = panel.groupby("season")["club_id"].nunique()
    for season in season_sizes.index:
        _check(
            season_sizes[season] == 380,
            f"{season}: expected 380 matches, got {season_sizes[season]}",
        )
        _check(
            club_counts[season] == 20,
            f"{season}: expected 20 clubs, got {club_counts[season]}",
        )
        sub = panel[panel["season"] == season]
        _check(sub["made_top4"].sum() == 4, f"{season}: made_top4 count != 4")
        _check(sub["relegated"].sum() == 3, f"{season}: relegated count != 3")
    _check(
        len(panel) == int(club_counts.sum()),
        f"panel rows {len(panel)} != sum of season club counts {club_counts.sum()}",
    )
    has_odds = panel["week1_odds_source"] != "none"
    _check(
        panel.loc[has_odds, "week1_shock"].notna().all(),
        "week1_shock is null despite W1 odds being present",
    )
    _check(
        panel.loc[~has_odds, "week1_shock"].isna().all(),
        "week1_shock is non-null where no W1 odds exist",
    )


def week1_match_diagnostics(all_matches: pd.DataFrame) -> pd.DataFrame:
    """Report how each season's 20 Week-1 team rows resolve to matches.

    Args:
        all_matches: the combined match frame.

    Returns:
        One row per season: ``season, n_w1_matches, clean`` where ``clean``
        means the 20 earliest-fixture rows collapse to exactly 10 distinct
        matches (every team's opener is also its opponent's opener).
    """
    records = []
    for season in sorted(all_matches["season"].unique()):
        matches = all_matches.loc[all_matches["season"] == season].reset_index(drop=True)
        w1 = week1_rows(matches)
        n_matches = w1["week1_match_idx"].nunique()
        records.append({"season": season, "n_w1_matches": n_matches, "clean": n_matches == 10})
    return pd.DataFrame.from_records(records)


def main() -> None:
    """Regenerate all frozen data and the team-season panel."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    all_matches = load_all_seasons()
    panel = build_panel(all_matches)
    validate(panel, all_matches)

    cache.freeze(panel, DATA_DIR, "panel")
    panel.to_csv(DATA_DIR / "panel.csv", index=False)

    diag = week1_match_diagnostics(all_matches)
    unclean = diag.loc[~diag["clean"], "season"].tolist()
    logger.info("panel rows: %d", len(panel))
    logger.info("%s", diag.to_string(index=False))
    logger.info("seasons where W1 did not resolve to 10 matches: %s", unclean or "none")
    coverage = panel.groupby(["season", "week1_odds_source"]).size().unstack(fill_value=0)
    logger.info("%s", coverage.to_string())
    logger.info(
        "%s", panel[["week1_shock", "week1_expected_points", "final_points"]].describe().to_string()
    )


if __name__ == "__main__":
    main()
