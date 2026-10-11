"""Integration tests — full pipeline on synthetic cohort data.

Tests the game_logs → E1/E3 → comparators_csv → figure pipeline end-to-end
without touching BRef (no network requests).
"""

import pathlib
import tempfile

import numpy as np
import pandas as pd
import pytest

import analyze_durability as ad


def _build_synthetic_cohort(n_players: int = 6, seasons: int = 10) -> pd.DataFrame:
    """Build a synthetic game-log DataFrame with n_players over multiple seasons.

    Player 0 is the 'treated' player (stockjo01) with near-zero missed games.
    Others have increasing miss rates.
    """
    rng = np.random.default_rng(99)
    rows = []
    for idx in range(n_players):
        pid = "stockjo01" if idx == 0 else f"player{idx:02d}"
        name = "John Stockton" if idx == 0 else f"Player {idx}"
        miss_rate = 0.02 if idx == 0 else 0.05 + idx * 0.04
        for season in range(2000, 2000 + seasons):
            season_games = 82
            active = int(season_games * (1 - miss_rate))
            for g in range(active):
                is_b2b = int(rng.random() < 0.15)
                rows.append({
                    "player_id": pid,
                    "player_name": name,
                    "season": season,
                    "Date": pd.Timestamp(f"{season}-01-01") + pd.Timedelta(days=g * 2),
                    "MP": "32:00",
                    "mp_float": 32.0,
                    "b2b": is_b2b,
                    "rest_days": 1.0 if is_b2b else 3.0,
                    "3PA": 2 + int(rng.random() < 0.3),
                    "FGA": 12,
                    "FTA": 3 + int(rng.random() < 0.2),
                })
    return pd.DataFrame(rows)


class TestE1Pipeline:
    """Full E1 pipeline: synthetic data → compute_e1 → permutation → comparators."""

    def setup_method(self):
        self.df = _build_synthetic_cohort(n_players=6, seasons=10)
        self.treated_id = "stockjo01"

    def test_e1_summary_has_all_players(self):
        summary, _ = ad.compute_e1(self.df, self.treated_id)
        assert len(summary) == 6

    def test_treated_player_has_fewest_missed(self):
        summary, treated_val = ad.compute_e1(self.df, self.treated_id)
        assert treated_val is not None
        min_val = summary["games_missed_per_82"].min()
        assert treated_val == pytest.approx(min_val, abs=0.5)

    def test_permutation_produces_valid_p(self):
        summary, _ = ad.compute_e1(self.df, self.treated_id)
        # Use temp dir to avoid writing test parquets to data/
        with tempfile.TemporaryDirectory() as tmp:
            orig_data = ad.DATA_DIR
            ad.DATA_DIR = pathlib.Path(tmp)
            try:
                obs, null, p = ad.permutation_e1(summary, self.treated_id, n_perm=100, cohort="synth")
                assert not np.isnan(obs)
                assert 0.0 <= p <= 1.0
                assert len(null) == 100
            finally:
                ad.DATA_DIR = orig_data

    def test_stockton_low_miss_rate_yields_extreme_p(self):
        """Treated player at extreme of distribution → p near 0 (strong signal)."""
        summary, _ = ad.compute_e1(self.df, self.treated_id)
        with tempfile.TemporaryDirectory() as tmp:
            orig_data = ad.DATA_DIR
            ad.DATA_DIR = pathlib.Path(tmp)
            try:
                obs, null, p = ad.permutation_e1(summary, self.treated_id, n_perm=200, cohort="synth2")
                # With treated at minimum and 6 players, perm p should be ≤ 1/6 ≈ 0.17
                assert p <= 0.25, f"Expected low p for extreme treated; got {p:.3f}"
            finally:
                ad.DATA_DIR = orig_data


class TestE3Pipeline:
    """E3 pipeline: synthetic B2B vs rest differences."""

    def setup_method(self):
        self.df = _build_synthetic_cohort(n_players=6, seasons=10)
        self.treated_id = "stockjo01"

    def test_e3_returns_all_players(self):
        e3 = ad.compute_e3(self.df, self.treated_id)
        # Each player should have enough B2B and rest games
        assert len(e3) == 6

    def test_e3_diff_columns_exist(self):
        e3 = ad.compute_e3(self.df, self.treated_id)
        assert "diff_3pa_fga" in e3.columns
        assert "diff_fta_fga" in e3.columns

    def test_cohens_d_range_reasonable(self):
        e3 = ad.compute_e3(self.df, self.treated_id)
        treated_row = e3[e3["player_id"] == self.treated_id]
        assert not treated_row.empty
        tx = float(treated_row["diff_3pa_fga"].iloc[0])
        d = ad.cohens_d(e3["diff_3pa_fga"].values, tx)
        # Effect size should be finite and reasonable
        assert np.isfinite(d)
        assert abs(d) < 10  # sanity bound


class TestComparatorsCSV:
    """emit_comparators_csv produces correctly ranked output."""

    def _make_summary(self) -> pd.DataFrame:
        return pd.DataFrame({
            "player_id": ["stockjo01", "player01", "player02", "player03",
                          "player04", "player05"],
            "player_name": ["John Stockton", "P1", "P2", "P3", "P4", "P5"],
            "games_missed_per_82": [1.5, 2.0, 3.5, 5.0, 7.0, 10.0],
        })

    def test_top3_comparators_are_closest(self):
        summary = self._make_summary()
        with tempfile.TemporaryDirectory() as tmp:
            orig_data = ad.DATA_DIR
            ad.DATA_DIR = pathlib.Path(tmp)
            try:
                ad.emit_comparators_csv(summary, "stockjo01", "pg", n_comps=3)
                out = pathlib.Path(tmp) / "pg_comparators.csv"
                assert out.exists()
                comps = pd.read_csv(out)
                assert len(comps) == 3
                # Closest to 1.5: player01 (2.0), player02 (3.5), player03 (5.0)
                assert "player01" in comps["player_id"].values
                assert "player02" in comps["player_id"].values
                assert "player03" in comps["player_id"].values
            finally:
                ad.DATA_DIR = orig_data

    def test_ranks_are_1_2_3(self):
        summary = self._make_summary()
        with tempfile.TemporaryDirectory() as tmp:
            orig_data = ad.DATA_DIR
            ad.DATA_DIR = pathlib.Path(tmp)
            try:
                ad.emit_comparators_csv(summary, "stockjo01", "pg", n_comps=3)
                comps = pd.read_csv(pathlib.Path(tmp) / "pg_comparators.csv")
                assert set(comps["rank"].values) == {1, 2, 3}
            finally:
                ad.DATA_DIR = orig_data
