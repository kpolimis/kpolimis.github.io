"""Tests for pure functions in fetch_wc_data.py.

Aggregation functions (build_league_stats, build_epl_club_stats) moved to
aggregate_wc_data.py — see tests/test_aggregate.py for those tests.

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
_AGG_PATH = Path(__file__).parent.parent / "posts" / "blog" / "world-cup-2026-leagues" / "aggregate_wc_data.py"

# Stub out soccerdata before the module loads so it doesn't require the browser.
sys.modules.setdefault("soccerdata", mock.MagicMock())

_spec = importlib.util.spec_from_file_location("fetch_wc_data", _FETCH_PATH)
fwd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fwd)

_agg_spec = importlib.util.spec_from_file_location("aggregate_wc_data", _AGG_PATH)
agg = importlib.util.module_from_spec(_agg_spec)
_agg_spec.loader.exec_module(agg)


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


# ── zero-record guards ────────────────────────────────────────────────────────

class TestZeroRecordGuards:
    def test_fetch_player_stats_raises_on_empty(self):
        """fetch_player_stats must raise ValueError if FBref returns 0 players."""
        empty_raw = pd.DataFrame(columns=["player", "team", "Club"])

        sd_mock = mock.MagicMock()
        fbref_mock = sd_mock.FBref.return_value
        # Simulate FBref returning an empty frame (with a MultiIndex reset → empty columns)
        empty_with_mi = mock.MagicMock()
        empty_with_mi.reset_index.return_value = empty_raw
        fbref_mock.read_player_season_stats.return_value = empty_with_mi

        with mock.patch.dict(sys.modules, {"soccerdata": sd_mock}):
            with pytest.raises(ValueError, match="0 players"):
                fwd.fetch_player_stats()

    def test_fetch_team_rounds_raises_on_empty_schedule(self):
        """fetch_team_rounds must raise ValueError if schedule produces no rounds."""
        empty_sched = pd.DataFrame(columns=["round", "home_team", "away_team"])

        sd_mock = mock.MagicMock()
        fbref_mock = sd_mock.FBref.return_value
        sched_mock = mock.MagicMock()
        sched_mock.reset_index.return_value = empty_sched
        fbref_mock.read_schedule.return_value = sched_mock

        with mock.patch.dict(sys.modules, {"soccerdata": sd_mock}):
            with pytest.raises(ValueError, match="no nations"):
                fwd.fetch_team_rounds()

    def test_build_epl_club_stats_empty_on_no_epl_players(self):
        """build_epl_club_stats returns an empty DataFrame (not an error) when no EPL players."""
        players_no_epl = pd.DataFrame({
            "player": ["A", "B"],
            "league": ["La Liga", "Bundesliga"],
            "club": ["Barcelona", "Bayern"],
            "minutes": [90.0, 90.0],
            "goals": [1.0, 0.0],
            "assists": [0.0, 1.0],
        })
        result = agg.build_epl_club_stats(players_no_epl)
        assert result.empty
        assert "club" in result.columns

