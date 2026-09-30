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

