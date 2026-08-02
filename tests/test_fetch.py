"""Tests for pure functions in fetch_wc_data.py.

All tests are I/O-free: no FBref calls, no file reads, no fixtures.
Run with: pytest tests/test_fetch.py -v
"""

import importlib.util
import sys
import unittest.mock as mock
from pathlib import Path

import pandas as pd
import pytest

# Load fetch_wc_data directly from its file path (directory name has hyphens,
# so standard package import is not possible).
_FETCH_PATH = Path(__file__).parent.parent / "posts" / "blog" / "world-cup-2026-leagues" / "fetch_wc_data.py"

# Stub out soccerdata before the module loads so it doesn't require the browser.
sys.modules.setdefault("soccerdata", mock.MagicMock())

_spec = importlib.util.spec_from_file_location("fetch_wc_data", _FETCH_PATH)
fwd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fwd)


# ── _strip_rank_prefix ────────────────────────────────────────────────────────

class TestStripRankPrefix:
    def test_strips_leading_rank(self):
        assert fwd._strip_rank_prefix("1. Arsenal") == "Arsenal"

    def test_strips_double_digit_rank(self):
        assert fwd._strip_rank_prefix("12. Leicester City") == "Leicester City"

    def test_no_prefix_unchanged(self):
        assert fwd._strip_rank_prefix("Barcelona") == "Barcelona"

    def test_strips_rank_with_extra_spaces(self):
        assert fwd._strip_rank_prefix("3.  Feyenoord") == "Feyenoord"

    def test_non_string_coerced(self):
        assert fwd._strip_rank_prefix(42) == "42"


# ── build_league_stats ────────────────────────────────────────────────────────

@pytest.fixture()
def players_df():
    return pd.DataFrame({
        "player":  ["A", "B", "C", "D"],
        "league":  ["EPL", "EPL", "La Liga", "La Liga"],
        "minutes": [180.0, 90.0, 270.0, 90.0],
        "goals":   [1.0, 0.0, 2.0, 1.0],
        "assists": [0.0, 1.0, 1.0, 0.0],
    })


class TestBuildLeagueStats:
    def test_row_count_matches_leagues(self, players_df):
        result = fwd.build_league_stats(players_df)
        assert len(result) == 2

    def test_epl_total_minutes(self, players_df):
        result = fwd.build_league_stats(players_df)
        epl = result[result["league"] == "EPL"].iloc[0]
        assert epl["total_minutes"] == 270.0

    def test_la_liga_ga_per90(self, players_df):
        result = fwd.build_league_stats(players_df)
        la_liga = result[result["league"] == "La Liga"].iloc[0]
        # (2+1+1+0) goals+assists over 360 min = 4/4 nineties = 1.0
        assert la_liga["ga_per90"] == pytest.approx(1.0, rel=1e-3)

    def test_sorted_by_minutes_descending(self, players_df):
        result = fwd.build_league_stats(players_df)
        assert result["total_minutes"].iloc[0] >= result["total_minutes"].iloc[1]


# ── build_epl_club_stats ──────────────────────────────────────────────────────

@pytest.fixture()
def epl_players_df():
    return pd.DataFrame({
        "player":  ["A", "B", "C", "D"],
        "league":  ["EPL", "EPL", "EPL", "La Liga"],
        "club":    ["Arsenal", "Arsenal", "Chelsea", "Barcelona"],
        "minutes": [90.0, 90.0, 180.0, 90.0],
        "goals":   [1.0, 0.0, 1.0, 5.0],
        "assists": [0.0, 1.0, 0.0, 5.0],
    })


class TestBuildEplClubStats:
    def test_excludes_non_epl(self, epl_players_df):
        result = fwd.build_epl_club_stats(epl_players_df)
        assert "Barcelona" not in result["club"].values

    def test_arsenal_player_count(self, epl_players_df):
        result = fwd.build_epl_club_stats(epl_players_df)
        arsenal = result[result["club"] == "Arsenal"].iloc[0]
        assert arsenal["player_count"] == 2

    def test_chelsea_ga_per90(self, epl_players_df):
        result = fwd.build_epl_club_stats(epl_players_df)
        chelsea = result[result["club"] == "Chelsea"].iloc[0]
        # 1 goal + 0 assists over 180 min = 1/2 nineties = 0.5
        assert chelsea["ga_per90"] == pytest.approx(0.5, rel=1e-3)
