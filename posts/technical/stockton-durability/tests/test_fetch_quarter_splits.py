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


class TestParsePbpQuarters:
    """Unit tests for the BRef play-by-play parser."""

    def _make_pbp_html(self, plays: list[str], quarters: int = 1) -> str:
        """Build minimal PBP HTML with given plays in quarter 1."""
        rows = [
            '<tr><td colspan="6">Start of 1st quarter</td></tr>',
        ]
        for play in plays:
            rows.append(f'<tr><td>11:59</td><td>{play}</td><td>0-0</td><td></td></tr>')
        table_html = f'<table id="pbp">{"".join(rows)}</table>'
        return f"<html><body>{table_html}</body></html>"

    def test_ft_made_counted(self):
        html = self._make_pbp_html(["John Stockton makes free throw 1 of 2"])
        rows = fqs.parse_pbp_quarters(
            html, "stockjo01", "John Stockton", "G1", 2000, None, "stockton_34_40"
        )
        assert len(rows) == 1
        assert rows[0]["FT"] == 1
        assert rows[0]["FTA"] == 1
        assert rows[0]["quarter"] == "1"

    def test_ft_missed_only_increments_fta(self):
        html = self._make_pbp_html(["John Stockton misses free throw 2 of 2"])
        rows = fqs.parse_pbp_quarters(
            html, "stockjo01", "John Stockton", "G1", 2000, None, "stockton_34_40"
        )
        assert rows[0]["FT"] == 0
        assert rows[0]["FTA"] == 1

    def test_fg_made_increments_fga_and_pts(self):
        html = self._make_pbp_html(["John Stockton makes two-point shot from 15 ft"])
        rows = fqs.parse_pbp_quarters(
            html, "stockjo01", "John Stockton", "G1", 2000, None, "stockton_34_40"
        )
        assert rows[0]["FGA"] == 1
        assert rows[0]["PTS"] == 2

    def test_three_pointer_scores_3(self):
        html = self._make_pbp_html(["John Stockton makes three-point shot from 24 ft"])
        rows = fqs.parse_pbp_quarters(
            html, "stockjo01", "John Stockton", "G1", 2000, None, "stockton_34_40"
        )
        assert rows[0]["PTS"] == 3

    def test_turnover_counted(self):
        html = self._make_pbp_html(["Turnover by John Stockton: Bad Pass"])
        rows = fqs.parse_pbp_quarters(
            html, "stockjo01", "John Stockton", "G1", 2000, None, "stockton_34_40"
        )
        assert rows[0]["TOV"] == 1

    def test_other_player_ignored(self):
        html = self._make_pbp_html(["Karl Malone makes jump shot"])
        rows = fqs.parse_pbp_quarters(
            html, "stockjo01", "John Stockton", "G1", 2000, None, "stockton_34_40"
        )
        # No rows for Stockton if he didn't play
        assert len(rows) == 0

    def test_returns_empty_on_missing_table(self):
        html = "<html><body><p>No PBP table here</p></body></html>"
        rows = fqs.parse_pbp_quarters(
            html, "stockjo01", "John Stockton", "G1", 2000, None, "stockton_34_40"
        )
        assert rows == []


class TestParseSeasonRange:
    def test_valid_range(self):
        assert fqs._parse_season_range("1996-2003") == (1996, 2003)

    def test_single_year_raises(self):
        with pytest.raises(ValueError):
            fqs._parse_season_range("1996")

    def test_none_returns_none(self):
        assert fqs._parse_season_range(None) is None
