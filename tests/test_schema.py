"""Tests for check_df_schema (analysis pipeline boundary validation).

All tests are I/O-free.
Run with: pytest tests/test_schema.py -v
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

# Add analysis/ to sys.path so @dataclass works correctly (needs its own module
# name to be importable — spec_from_file_location without sys.modules registration
# breaks @dataclass on Python 3.14).
_ANALYSIS_DIR = str(
    Path(__file__).parent.parent
    / "posts" / "blog" / "epl-2026-27-predictions" / "analysis"
)
if _ANALYSIS_DIR not in sys.path:
    sys.path.insert(0, _ANALYSIS_DIR)

from params import check_df_schema  # noqa: E402


# ── check_df_schema ───────────────────────────────────────────────────────────

class TestCheckDfSchema:
    def _minimal(self) -> pd.DataFrame:
        return pd.DataFrame({"season": ["0809"], "club_id": ["Arsenal"]})

    def test_passes_when_all_columns_present(self):
        check_df_schema(self._minimal(), ["season", "club_id"], "test_df")

    def test_raises_on_missing_column(self):
        with pytest.raises(ValueError, match="missing required columns"):
            check_df_schema(self._minimal(), ["season", "club_id", "fthg"], "test_df")

    def test_error_message_names_missing_columns(self):
        with pytest.raises(ValueError, match="fthg"):
            check_df_schema(self._minimal(), ["season", "fthg"], "test_df")

    def test_raises_on_empty_dataframe(self):
        empty = pd.DataFrame(columns=["season", "club_id"])
        with pytest.raises(ValueError, match="empty"):
            check_df_schema(empty, ["season", "club_id"], "test_df")

    def test_accepts_superset_of_required_columns(self):
        df = pd.DataFrame({"season": ["0809"], "club_id": ["Arsenal"], "extra": [1]})
        check_df_schema(df, ["season", "club_id"], "test_df")

    def test_name_appears_in_error_message(self):
        with pytest.raises(ValueError, match="my_dataset"):
            check_df_schema(self._minimal(), ["nonexistent"], "my_dataset")
