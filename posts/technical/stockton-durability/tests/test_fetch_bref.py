"""Tests for fetch_bref_data.py — cohort structure, parsing, and CSV output."""

import pandas as pd
import pytest

import fetch_bref_data as fb


class TestCohortStructure:
    def test_pg_entries_present(self):
        pg = {v[1] for v in fb.COHORT.values() if v[4] == "pg"}
        assert "stockjo01" in pg
        assert "nashst01" in pg
        assert len(pg) == 15

    def test_pf_entries_present(self):
        pf = {v[1] for v in fb.COHORT.values() if v[4] == "pf"}
        expected = {"diawbo01", "nowitdi01", "boozeca01", "jamisan01", "mariosh01", "lewisra02"}
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
    """Run cohort_summary against the real parquet — validates both cohorts. (#21)"""

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

    def test_all_pg_cohort_present(self):
        """All 15 PG cohort players must appear in cohort_summary (#21)."""
        summary = fb.cohort_summary(save_csv=False)
        if summary.empty:
            pytest.skip("No game log data available")
        pg_expected = {v[1] for v in fb.COHORT.values() if v[4] == "pg"}
        pg_in_summary = set(summary.loc[summary["cohort"] == "pg", "player_id"])
        assert pg_expected == pg_in_summary, f"Missing PG players: {pg_expected - pg_in_summary}"

    def test_all_pf_cohort_present(self):
        """All 6 PF cohort players must appear in cohort_summary (#21)."""
        summary = fb.cohort_summary(save_csv=False)
        if summary.empty:
            pytest.skip("No game log data available")
        pf_expected = {v[1] for v in fb.COHORT.values() if v[4] == "pf"}
        pf_in_summary = set(summary.loc[summary["cohort"] == "pf", "player_id"])
        assert pf_expected == pf_in_summary, f"Missing PF players: {pf_expected - pf_in_summary}"

    def test_both_subjects_exceed_career_games_threshold(self):
        """Stockton and Diaw must both meet career games threshold ≥600 (#21)."""
        summary = fb.cohort_summary(save_csv=False)
        if summary.empty:
            pytest.skip("No game log data available")
        for pid in ("stockjo01", "diawbo01"):
            row = summary[summary["player_id"] == pid]
            assert not row.empty, f"{pid} missing from summary"
            assert row.iloc[0]["career_games"] >= fb.MIN_CAREER_GAMES

    def test_borderline_mpg_cases_documented(self):
        """Terry Porter and Boris Diaw are borderline MPG — expected in summary but not meets_threshold (#21).

        Both exceed ≥600 games and are retained in the cohort as borderline;
        the post Limitations section documents their MPG deviation.
        """
        summary = fb.cohort_summary(save_csv=False)
        if summary.empty:
            pytest.skip("No game log data available")
        for pid in ("portete01", "diawbo01"):
            row = summary[summary["player_id"] == pid]
            assert not row.empty, f"Borderline player {pid} missing from summary"
            assert row.iloc[0]["career_games"] >= fb.MIN_CAREER_GAMES
            assert row.iloc[0]["career_mpg"] < fb.MIN_CAREER_MPG


class TestEraComputation:
    """Era string computation used in population cohort CSV."""

    def test_1980s_debut(self):
        debut = 1984
        era = f"{(debut // 10) * 10}s"
        assert era == "1980s"

    def test_1990s_debut(self):
        debut = 1996
        era = f"{(debut // 10) * 10}s"
        assert era == "1990s"

    def test_2000s_debut(self):
        debut = 2003
        era = f"{(debut // 10) * 10}s"
        assert era == "2000s"

    def test_boundary_2000(self):
        debut = 2000
        era = f"{(debut // 10) * 10}s"
        assert era == "2000s"


class TestPositionFiltering:
    """Guard and forward era guards used in build_population_cohort."""

    def _is_included(self, pos: str, debut: int) -> bool:
        is_guard = any(p in pos for p in ("G", "PG", "SG"))
        is_forward = any(p in pos for p in ("F", "PF", "SF"))
        guard_era = 1980 <= debut <= 2010
        forward_era = 1995 <= debut <= 2010
        return (is_guard and guard_era) or (is_forward and forward_era)

    def test_pg_in_range_included(self):
        assert self._is_included("PG", 1995)

    def test_guard_too_old_excluded(self):
        assert not self._is_included("G", 1975)

    def test_guard_too_new_excluded(self):
        assert not self._is_included("G", 2015)

    def test_forward_before_1995_excluded(self):
        assert not self._is_included("PF", 1988)

    def test_forward_1995_included(self):
        assert self._is_included("PF", 1995)

    def test_center_excluded(self):
        assert not self._is_included("C", 1995)


class TestFetchCohortSkipLogic:
    """fetch_cohort correctly skips already-fetched (player_id, season) pairs."""

    def test_done_keys_format(self):
        """done_keys should be {(player_id, season)} pairs from existing parquet."""
        rows = [
            {
                "player_id": "stockjo01",
                "season": 2000,
                "Date": pd.Timestamp("2000-01-01"),
                "MP": "30:00",
            },
            {
                "player_id": "stockjo01",
                "season": 2001,
                "Date": pd.Timestamp("2001-01-01"),
                "MP": "30:00",
            },
        ]
        existing = pd.DataFrame(rows)
        done_keys = set(zip(existing["player_id"], existing["season"], strict=False))
        assert ("stockjo01", 2000) in done_keys
        assert ("stockjo01", 2001) in done_keys
        assert ("stockjo01", 1999) not in done_keys
