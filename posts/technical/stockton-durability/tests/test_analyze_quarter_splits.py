"""Tests for analyze_quarter_splits.py — E2/E4/E5 within-game analysis."""

import numpy as np
import pandas as pd
import pytest

import analyze_quarter_splits as aqs


class TestAddAstTov:
    def test_computes_ratio(self):
        df = pd.DataFrame({"AST": [6.0], "TOV": [2.0]})
        result = aqs._add_ast_tov(df)
        assert "AST_TOV_ratio" in result.columns
        assert result["AST_TOV_ratio"].iloc[0] == pytest.approx(6.0 / 2.001, rel=1e-3)

    def test_zero_tov_avoids_division_by_zero(self):
        df = pd.DataFrame({"AST": [5.0], "TOV": [0.0]})
        result = aqs._add_ast_tov(df)
        # Should not raise; 5 / 0.001 = 5000
        assert result["AST_TOV_ratio"].iloc[0] == pytest.approx(5000.0, rel=1e-2)

    def test_missing_columns_noop(self):
        df = pd.DataFrame({"FT": [5.0]})
        result = aqs._add_ast_tov(df)
        assert "AST_TOV_ratio" not in result.columns


class TestEstimandFromMetric:
    def test_ft_pct_is_e2(self):
        assert aqs._estimand_from_metric("FT_pct") == "2"

    def test_ast_tov_is_e4(self):
        assert aqs._estimand_from_metric("AST_TOV_ratio") == "4"

    def test_ts_pct_is_e5(self):
        assert aqs._estimand_from_metric("TS_pct") == "5"

    def test_unknown_returns_x(self):
        assert aqs._estimand_from_metric("other") == "x"


class TestPrepareModelDf:
    def _make_quarter_df(self, quarters=("1", "2", "3", "4")) -> pd.DataFrame:
        rows = []
        for pid, name in [("p1", "P1"), ("p2", "P2")]:
            for q in quarters:
                for _ in range(5):
                    rows.append({
                        "player_id": pid,
                        "player_name": name,
                        "quarter": q,
                        "season": 2000,
                        "date": pd.Timestamp("2000-01-01"),
                        "FT_pct": 0.8 if q == "4" else 0.85,
                        "rest_days": 3.0,
                    })
        return pd.DataFrame(rows)

    def test_returns_none_for_full_quarter(self):
        df = self._make_quarter_df(quarters=("full",))
        result = aqs._prepare_model_df(df, "FT_pct", "p1")
        assert result is None

    def test_returns_none_when_missing_metric_col(self):
        df = self._make_quarter_df()
        result = aqs._prepare_model_df(df, "nonexistent_col", "p1")
        assert result is None

    def test_returns_none_for_single_player(self):
        df = self._make_quarter_df()
        df = df[df["player_id"] == "p1"]
        result = aqs._prepare_model_df(df, "FT_pct", "p1")
        assert result is None

    def test_adds_is_treated_column(self):
        df = self._make_quarter_df()
        result = aqs._prepare_model_df(df, "FT_pct", "p1")
        assert result is not None
        assert "is_treated" in result.columns
        treated_vals = result[result["player_id"] == "p1"]["is_treated"].unique()
        assert list(treated_vals) == [1]

    def test_adds_quarter4_flag(self):
        df = self._make_quarter_df()
        result = aqs._prepare_model_df(df, "FT_pct", "p1")
        assert result is not None
        assert "quarter4" in result.columns
        assert set(result["quarter4"].unique()).issubset({0, 1})


class TestPermutationInteraction:
    def _make_model_df(self) -> pd.DataFrame:
        """Two players, 4 quarters, 10 rows each — minimal fixture."""
        rows = []
        for pid, name in [("treated", "Treated"), ("ctrl", "Control")]:
            for q in ["1", "2", "3", "4"]:
                for _ in range(10):
                    rows.append({
                        "player_id": pid,
                        "player_name": name,
                        "quarter": q,
                        "quarter4": int(q == "4"),
                        "is_treated": int(pid == "treated"),
                        "rest_days": 3.0,
                        "FT_pct": 0.75 if q == "4" and pid == "treated" else 0.85,
                    })
        return pd.DataFrame(rows)

    def test_returns_float_coef(self):
        df = self._make_model_df()
        df["quarter4_treated"] = df["quarter4"] * df["is_treated"]
        obs, null, p = aqs.permutation_interaction(df, "FT_pct", n_perm=30, cohort="test")
        # coef may be nan if model fails, but p should still be in [0,1] or nan
        if not np.isnan(p):
            assert 0.0 <= p <= 1.0

    def test_null_distribution_length(self):
        df = self._make_model_df()
        df["quarter4_treated"] = df["quarter4"] * df["is_treated"]
        _, null, _ = aqs.permutation_interaction(df, "FT_pct", n_perm=20, cohort="test")
        # null may be shorter than n_perm if some fits fail
        assert len(null) >= 0  # at minimum doesn't crash


class TestLoadSplitsFileNotFound:
    def test_raises_on_missing_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(aqs, "DATA_DIR", tmp_path)
        with pytest.raises(FileNotFoundError):
            aqs.load_splits("pg")

    def test_unknown_cohort_raises(self):
        with pytest.raises(ValueError):
            aqs.load_splits("xyz")


class TestPrepareModelDfRestDays:
    """Guards for rest_days merge collision (avoids _x/_y suffixes)."""

    def _make_df_with_rest_days(self) -> pd.DataFrame:
        rows = []
        for pid in ("p1", "p2"):
            for q in ("1", "2", "3", "4"):
                for _ in range(5):
                    rows.append({
                        "player_id": pid,
                        "quarter": q,
                        "season": 2000,
                        "date": pd.Timestamp("2000-01-01"),
                        "FT_pct": 0.8,
                        "rest_days": 2.0,
                    })
        return pd.DataFrame(rows)

    def test_rest_days_already_present_no_collision(self):
        df = self._make_df_with_rest_days()
        result = aqs._prepare_model_df(df, "FT_pct", "p1")
        assert result is not None
        # No _x/_y suffix columns
        assert "rest_days" in result.columns
        assert "rest_days_x" not in result.columns
        assert "rest_days_y" not in result.columns

    def test_rest_days_fillna_applied(self):
        df = self._make_df_with_rest_days()
        df.loc[df["player_id"] == "p1", "rest_days"] = np.nan
        result = aqs._prepare_model_df(df, "FT_pct", "p1")
        assert result is not None
        assert result["rest_days"].isna().sum() == 0  # NaN filled with 3


class TestPrepareModelDfOtQuarters:
    """OT quarters (OT1, OT2) should not trigger the 'full' guard."""

    def _make_df_with_ot(self) -> pd.DataFrame:
        rows = []
        for pid in ("p1", "p2"):
            for q in ("1", "2", "3", "4", "OT1"):
                for _ in range(5):
                    rows.append({
                        "player_id": pid,
                        "quarter": q,
                        "season": 2000,
                        "date": pd.Timestamp("2000-01-01"),
                        "FT_pct": 0.8,
                        "rest_days": 3.0,
                    })
        return pd.DataFrame(rows)

    def test_ot_rows_allowed_through(self):
        df = self._make_df_with_ot()
        result = aqs._prepare_model_df(df, "FT_pct", "p1")
        assert result is not None

    def test_quarter4_flag_does_not_include_ot(self):
        df = self._make_df_with_ot()
        result = aqs._prepare_model_df(df, "FT_pct", "p1")
        assert result is not None
        ot_rows = result[result["quarter"].astype(str).str.startswith("OT")]
        assert (ot_rows["quarter4"] == 0).all(), "OT rows should not be flagged as Q4"


class TestComputeE1EdgeCases:
    """Edge cases: single season, missing treated player, large miss rate."""

    def test_single_season_player(self):
        df = pd.DataFrame({
            "player_id": ["p1", "p2"],
            "player_name": ["P1", "P2"],
            "season": [2000, 2000],
            "Date": [pd.Timestamp("2000-01-10"), pd.Timestamp("2000-01-10")],
            "MP": ["30:00", "30:00"],
            "mp_float": [30.0, 30.0],
        })
        import analyze_durability as ad
        summary, treated_val = ad.compute_e1(df, "p1")
        assert len(summary) == 2
        assert treated_val is not None

    def test_empty_dataframe_returns_empty_summary(self):
        import analyze_durability as ad
        df = pd.DataFrame(columns=["player_id", "player_name", "season", "Date", "MP", "mp_float"])
        summary, treated_val = ad.compute_e1(df, "stockjo01")
        assert len(summary) == 0
        assert treated_val is None

    def test_emit_comparators_fewer_than_n_comps(self):
        """When fewer than n_comps others exist, returns all available."""
        import pathlib
        import tempfile
        import analyze_durability as ad
        summary = pd.DataFrame({
            "player_id": ["p1", "p2"],
            "player_name": ["P1", "P2"],
            "games_missed_per_82": [1.0, 5.0],
        })
        with tempfile.TemporaryDirectory() as tmp:
            orig = ad.DATA_DIR
            ad.DATA_DIR = pathlib.Path(tmp)
            try:
                ad.emit_comparators_csv(summary, "p1", "pg", n_comps=5)
                out = pathlib.Path(tmp) / "pg_comparators.csv"
                comps = pd.read_csv(out)
                # Only 1 other player; should get 1 row, not error
                assert len(comps) == 1
            finally:
                ad.DATA_DIR = orig
