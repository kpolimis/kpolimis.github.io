"""Tests for fetch_bref_data.py — cohort structure, parsing, and CSV output."""

import pathlib
import sys

import pandas as pd
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import fetch_bref_data as fb


class TestCohortStructure:
    def test_pg_entries_present(self):
        pg = {v[1] for v in fb.COHORT.values() if v[4] == "pg"}
        assert "stockjo01" in pg
        assert "nashst01" in pg
        assert len(pg) == 15

    def test_pf_entries_present(self):
        pf = {v[1] for v in fb.COHORT.values() if v[4] == "pf"}
        expected = {"diawbo01", "nowitdi01", "boozeca01", "jamisna01", "mariosh01", "lewisra02"}
        assert pf == expected

    def test_all_tuples_have_five_elements(self):
        for name, val in fb.COHORT.items():
            assert len(val) == 5, f"{name} tuple has {len(val)} elements, expected 5"

    def test_cohort_types_valid(self):
        valid = {"pg", "pf"}
        for name, val in fb.COHORT.items():
            assert val[4] in valid, f"{name} has unknown cohort type {val[4]!r}"

    def test_lewis_disambiguation(self):
        lewis = fb.COHORT["Rashard Lewis"]
        assert lewis[1] == "lewisra02", "Rashard Lewis must use 02 not 01"

    def test_pf_season_ranges_non_empty(self):
        for name, val in fb.COHORT.items():
            if val[4] == "pf":
                first, last = val[2], val[3]
                assert first <= last, f"{name}: first season {first} > last {last}"
                assert last - first >= 5, f"{name}: career only {last - first} seasons"


class TestParseMpSeconds:
    def test_standard_format(self):
        assert fb.parse_mp_seconds("34:21") == pytest.approx(34 + 21 / 60, rel=1e-3)

    def test_zero_seconds(self):
        assert fb.parse_mp_seconds("12:00") == 12.0

    def test_none_for_non_string(self):
        assert fb.parse_mp_seconds(None) is None

    def test_none_for_no_colon(self):
        assert fb.parse_mp_seconds("inactive") is None

    def test_none_for_empty(self):
        assert fb.parse_mp_seconds("") is None


class TestCohortSummary:
    """Run cohort_summary against the real parquet (Stockton-only so far)."""

    def test_returns_dataframe(self):
        summary = fb.cohort_summary(save_csv=False)
        assert isinstance(summary, pd.DataFrame)

    def test_stockton_present(self):
        summary = fb.cohort_summary(save_csv=False)
        if summary.empty:
            pytest.skip("No game log data available")
        assert "stockjo01" in summary["player_id"].values

    def test_stockton_meets_threshold(self):
        summary = fb.cohort_summary(save_csv=False)
        if summary.empty:
            pytest.skip("No game log data available")
        row = summary[summary["player_id"] == "stockjo01"].iloc[0]
        assert row["career_games"] == 1504
        assert row["meets_threshold"]

    def test_stockton_row_count_assertion(self):
        """Verify the hardcoded assertion inside cohort_summary doesn't raise."""
        try:
            fb.cohort_summary(save_csv=False)
        except AssertionError:
            pytest.fail("Stockton row count assertion failed — parquet may be corrupt.")
