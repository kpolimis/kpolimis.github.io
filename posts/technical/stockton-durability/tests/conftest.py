"""Pytest configuration for stockton-durability test suite.

Adds the parent directory (stockton-durability/) to sys.path so that
test modules can import analysis scripts without needing manual path inserts.
"""

import pathlib
import sys

# Ensure the stockton-durability directory is on sys.path for all tests
ANALYSIS_DIR = pathlib.Path(__file__).parent.parent
if str(ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(ANALYSIS_DIR))
