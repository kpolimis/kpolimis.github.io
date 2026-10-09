"""Tests for fetch_quarter_splits.py — game_id extraction and TS% computation."""

import pathlib
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import fetch_quarter_splits as fqs


class TestTsPct:
    def test_standard_calculation(self):
        ts = fqs._ts_pct(20, 15, 5)
        # 20 / (2 * (15 + 0.44*5)) = 20 / (2 * 17.2) = 20/34.4
        expected = 20 / (2 * (15 + 0.44 * 5))
        assert ts == pytest.approx(expected, rel=1e-4)

    def test_zero_attempts_returns_none(self):
        assert fqs._ts_pct(0, 0, 0) is None

    def test_zero_pts_returns_zero(self):
        ts = fqs._ts_pct(0, 10, 2)
        assert ts == pytest.approx(0.0, abs=1e-6)


class TestParseMp:
    def test_valid(self):
        assert fqs._parse_mp("30:00") == pytest.approx(30.0)

    def test_invalid_returns_none(self):
        assert fqs._parse_mp("Did Not Play") is None

    def test_none_returns_none(self):
        assert fqs._parse_mp(None) is None


class TestExtractGameId:
    def _home_row(self) -> pd.Series:
        return pd.Series({
            "Date": pd.Timestamp("1999-03-15"),
            "Tm": "UTA",
            "Unnamed: 5": "",
            "Opp": "CHI",
        })

    def _away_row(self) -> pd.Series:
        return pd.Series({
            "Date": pd.Timestamp("1999-03-15"),
            "Tm": "UTA",
            "Unnamed: 5": "@",
            "Opp": "CHI",
        })

    def test_home_game_id(self):
        gid = fqs._extract_game_id(self._home_row())
        assert gid == "199903150UTA"

    def test_away_game_id_uses_opponent(self):
        gid = fqs._extract_game_id(self._away_row())
        assert gid == "199903150CHI"

    def test_nan_date_returns_none(self):
        row = pd.Series({"Date": None, "Tm": "UTA", "Unnamed: 5": "", "Opp": "LAL"})
        assert fqs._extract_game_id(row) is None


class TestAgeRegime:
    def test_stockton_always_labeled(self):
        assert fqs._age_regime("stockjo01", 1997) == "stockton_34_40"
        assert fqs._age_regime("stockjo01", 2000) == "stockton_34_40"

    def test_other_player_not_stockton_label(self):
        regime = fqs._age_regime("diawbo01", 2008)
        assert "stockton" not in regime


class TestParseSeasonRange:
    def test_valid_range(self):
        assert fqs._parse_season_range("1996-2003") == (1996, 2003)

    def test_single_year_raises(self):
        with pytest.raises(ValueError):
            fqs._parse_season_range("1996")

    def test_none_returns_none(self):
        assert fqs._parse_season_range(None) is None
