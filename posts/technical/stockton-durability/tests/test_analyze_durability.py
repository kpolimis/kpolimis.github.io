"""Tests for analyze_durability.py — E1/E3 analysis engine."""

import numpy as np
import pandas as pd
import pytest

import analyze_durability as ad


class TestSeasonGames:
    def test_standard_season_is_82(self):
        assert ad.SEASON_GAMES[2000] == 82
        assert ad.SEASON_GAMES[2010] == 82

    def test_shortened_seasons(self):
        assert ad.SEASON_GAMES[1999] == 50
        assert ad.SEASON_GAMES[2012] == 66
        assert ad.SEASON_GAMES[2020] == 65
        assert ad.SEASON_GAMES[2021] == 72


class TestParseMp:
    def test_valid(self):
        assert ad._parse_mp("34:21") == pytest.approx(34 + 21 / 60, rel=1e-3)

    def test_none_for_invalid(self):
        assert ad._parse_mp("DNP") is None
        assert ad._parse_mp(None) is None


class TestComputeE1:
    def _make_df(self) -> pd.DataFrame:
        """Build a minimal game-log DataFrame for two players."""
        rows = []
        for pid, name, n_games in [("playerA", "Player A", 80), ("playerB", "Player B", 70)]:
            for i in range(n_games):
                rows.append({
                    "player_id": pid,
                    "player_name": name,
                    "season": 2000,
                    "Date": pd.Timestamp("2000-01-01") + pd.Timedelta(days=i),
                    "MP": f"32:{i % 60:02d}",
                    "b2b": int(i % 5 == 0),
                    "rest_days": 1.0 if i % 5 == 0 else 3.0,
                    "3PA": 2, "FGA": 10, "FTA": 3,
                })
        df = pd.DataFrame(rows)
        df["mp_float"] = df["MP"].apply(ad._parse_mp)
        return df

    def test_games_missed_per_82_computes(self):
        df = self._make_df()
        summary, treated_val = ad.compute_e1(df, "playerA")
        assert "games_missed_per_82" in summary.columns
        assert not summary.empty

    def test_treated_player_extracted(self):
        df = self._make_df()
        _, treated_val = ad.compute_e1(df, "playerA")
        assert treated_val is not None
        assert isinstance(treated_val, float)

    def test_games_missed_non_negative(self):
        df = self._make_df()
        summary, _ = ad.compute_e1(df, "playerA")
        assert (summary["games_missed_per_82"] >= 0).all()

    def test_missing_treated_id_returns_none(self):
        df = self._make_df()
        _, treated_val = ad.compute_e1(df, "nonexistent_id")
        assert treated_val is None

    def test_season_games_used_correctly(self):
        """Player with 50 active games in 1999 season (50-game season) → 0 missed."""
        rows = [{"player_id": "p1", "player_name": "P1", "season": 1999,
                 "Date": pd.Timestamp("1999-01-01") + pd.Timedelta(days=i),
                 "MP": "32:00", "mp_float": 32.0,
                 "b2b": 0, "rest_days": 3.0, "3PA": 0, "FGA": 5, "FTA": 1}
                for i in range(50)]
        df = pd.DataFrame(rows)
        summary, _ = ad.compute_e1(df, "p1")
        row = summary[summary["player_id"] == "p1"].iloc[0]
        assert row["games_missed"] == 0
        assert row["games_missed_per_82"] == pytest.approx(0.0, abs=0.01)


class TestComputeE3:
    def _make_df(self) -> pd.DataFrame:
        """Two players, each with B2B and rest games."""
        rows = []
        for pid, name in [("p1", "P1"), ("p2", "P2")]:
            for i in range(100):
                is_b2b = int(i % 5 == 0)
                rows.append({
                    "player_id": pid,
                    "player_name": name,
                    "b2b": is_b2b,
                    "3PA": 3 if is_b2b else 5,
                    "FGA": 10,
                    "FTA": 2 if is_b2b else 4,
                    "mp_float": 30.0,
                })
        return pd.DataFrame(rows)

    def test_returns_dataframe(self):
        df = self._make_df()
        result = ad.compute_e3(df, "p1")
        assert isinstance(result, pd.DataFrame)
        assert len(result) == 2

    def test_b2b_uses_fewer_FTAs(self):
        df = self._make_df()
        result = ad.compute_e3(df, "p1")
        # B2B FTA/FGA should be lower than rest
        for _, row in result.iterrows():
            assert row["diff_fta_fga"] < 0, \
                f"Expected negative diff_fta_fga for {row['player_name']}"

    def test_insufficient_b2b_excluded(self):
        """Players with <5 B2B games should be excluded."""
        rows = [{"player_id": "p1", "player_name": "P1", "b2b": 0,
                 "3PA": 2, "FGA": 8, "FTA": 3, "mp_float": 30.0}
                for _ in range(50)]
        rows += [{"player_id": "p1", "player_name": "P1", "b2b": 1,
                  "3PA": 1, "FGA": 6, "FTA": 2, "mp_float": 30.0}
                 for _ in range(3)]
        df = pd.DataFrame(rows)
        result = ad.compute_e3(df, "p1")
        assert result.empty


class TestCohensD:
    def test_zero_effect(self):
        vals = np.array([1.0, 2.0, 3.0])
        assert ad.cohens_d(vals, 2.0) == pytest.approx(0.0, abs=1e-6)

    def test_positive_effect(self):
        vals = np.array([0.0, 1.0, 2.0])
        d = ad.cohens_d(vals, 3.0)
        assert d > 0

    def test_single_value_returns_nan(self):
        assert np.isnan(ad.cohens_d(np.array([1.0]), 2.0))


class TestPermutationE1:
    """Permutation test produces well-behaved null distributions."""

    def _make_summary(self) -> pd.DataFrame:
        return pd.DataFrame({
            "player_id": ["p1", "p2", "p3", "p4", "p5"],
            "player_name": ["P1", "P2", "P3", "P4", "P5"],
            "games_missed_per_82": [1.0, 3.0, 5.0, 7.0, 9.0],
        })

    def test_null_has_correct_length(self):
        summary = self._make_summary()
        _, null, _ = ad.permutation_e1(summary, "p1", n_perm=50, cohort="test")
        assert len(null) == 50

    def test_p_value_in_range(self):
        summary = self._make_summary()
        _, _, p = ad.permutation_e1(summary, "p1", n_perm=100, cohort="test")
        assert 0.0 <= p <= 1.0

    def test_treated_not_in_others_each_iteration(self):
        """Observed gap is never inflated by the treated player being in 'others'."""
        # If treated is at the extreme, observed gap should be large
        summary = pd.DataFrame({
            "player_id": ["treated", "p2", "p3", "p4", "p5"],
            "player_name": ["Treated", "P2", "P3", "P4", "P5"],
            "games_missed_per_82": [0.0, 5.0, 6.0, 7.0, 8.0],
        })
        obs_gap, _, _ = ad.permutation_e1(summary, "treated", n_perm=200, cohort="test2")
        # Treated at 0.0, median of [5,6,7,8] = 6.5 → gap = 0 - 6.5 = -6.5
        assert obs_gap == pytest.approx(-6.5, abs=0.01)

    def test_missing_treated_id_returns_nan(self):
        summary = self._make_summary()
        obs, _, p = ad.permutation_e1(summary, "nonexistent", n_perm=10, cohort="test3")
        assert np.isnan(obs)
        assert np.isnan(p)


class TestLoadCohort:
    def test_pg_cohort_loads(self):
        df, tid, tname = ad.load_cohort("pg")
        assert not df.empty
        assert tid == "stockjo01"
        assert tname == "John Stockton"

    def test_unknown_cohort_raises(self):
        with pytest.raises(ValueError, match="Unknown cohort"):
            ad.load_cohort("xyz")

    def test_pg_filtered_to_pg_ids(self):
        df, _, _ = ad.load_cohort("pg")
        assert df["player_id"].isin(ad.PG_IDS).all()

    def test_population_cohort_loads_with_no_treated(self):
        """Population cohort returns treated_id=None, treated_name=None (#32)."""
        df, tid, tname = ad.load_cohort("population")
        assert not df.empty
        assert tid is None
        assert tname is None

    def test_population_includes_stockton_and_diaw(self):
        """Stockton and Diaw must appear in population cohort load (#32)."""
        df, _, _ = ad.load_cohort("population")
        pids = set(df["player_id"].unique())
        assert "stockjo01" in pids, "Stockton missing from population"
        assert "diawbo01" in pids, "Diaw missing from population"

    def test_population_e1_stockton_is_most_durable(self):
        """Stockton's games_missed_per_82 should be lowest in population E1 (#32)."""
        df, tid, _ = ad.load_cohort("population")
        summary, _ = ad.compute_e1(df, tid)
        assert not summary.empty
        stockton_row = summary[summary["player_id"] == "stockjo01"]
        assert not stockton_row.empty
        stockton_val = stockton_row.iloc[0]["games_missed_per_82"]
        median_val = summary["games_missed_per_82"].median()
        assert stockton_val < median_val, (
            f"Stockton ({stockton_val:.2f}) should be below median ({median_val:.2f})"
        )

    def test_population_e1_diaw_below_median(self):
        """Diaw's games_missed_per_82 should be well below median in population (#32)."""
        df, tid, _ = ad.load_cohort("population")
        summary, _ = ad.compute_e1(df, tid)
        diaw_row = summary[summary["player_id"] == "diawbo01"]
        assert not diaw_row.empty
        diaw_val = diaw_row.iloc[0]["games_missed_per_82"]
        median_val = summary["games_missed_per_82"].median()
        assert diaw_val < median_val, (
            f"Diaw ({diaw_val:.2f}) should be below median ({median_val:.2f})"
        )


class TestComputeE1GamesClamped:
    """Games-missed is clipped to zero — can't be negative."""

    def test_player_with_more_games_than_schedule_clamps_to_zero(self):
        """If a player appears in 83 games in an 82-game season (data error),
        games_missed should clamp to 0, not go negative."""
        rows = [{"player_id": "p1", "player_name": "P1", "season": 2000,
                 "Date": pd.Timestamp("2000-01-01") + pd.Timedelta(days=i),
                 "MP": "32:00", "mp_float": 32.0}
                for i in range(83)]  # 83 > 82
        df = pd.DataFrame(rows)
        summary, _ = ad.compute_e1(df, "p1")
        assert summary.iloc[0]["games_missed"] == 0
        assert summary.iloc[0]["games_missed_per_82"] == pytest.approx(0.0, abs=0.01)


class TestPlotFunctions:
    """Plot functions should not raise on valid input."""

    def _make_summary(self) -> pd.DataFrame:
        return pd.DataFrame({
            "player_id": ["p1", "p2", "p3"],
            "player_name": ["P1", "P2", "P3"],
            "games_missed_per_82": [1.0, 3.0, 5.0],
        })

    def test_e1_histogram_no_crash(self, tmp_path):
        orig = ad.DATA_DIR
        ad.DATA_DIR = tmp_path
        try:
            ad.plot_e1_histogram(self._make_summary(), "p1", "Player 1", "test_cohort")
            out = tmp_path / "figures" / "test_cohort" / "e1_histogram.png"
            assert out.exists()
        finally:
            ad.DATA_DIR = orig

    def test_e1_histogram_without_treated_id_no_crash(self, tmp_path):
        orig = ad.DATA_DIR
        ad.DATA_DIR = tmp_path
        try:
            ad.plot_e1_histogram(self._make_summary(), None, None, "test_cohort")
        finally:
            ad.DATA_DIR = orig

    def test_e3_scatter_no_crash(self, tmp_path):
        e3_df = pd.DataFrame({
            "player_id": ["p1", "p2"],
            "player_name": ["P1", "P2"],
            "diff_3pa_fga": [0.02, -0.01],
            "diff_fta_fga": [-0.05, 0.03],
        })
        orig = ad.DATA_DIR
        ad.DATA_DIR = tmp_path
        try:
            ad.plot_e3_scatter(e3_df, "p1", "Player 1", "test_cohort")
            out = tmp_path / "figures" / "test_cohort" / "e3_scatter.png"
            assert out.exists()
        finally:
            ad.DATA_DIR = orig
