"""Test package root for avenoxbeyin test suite.

Ensures the tests/ directory is present on sys.path so test helper modules
(such as `v3_package_helpers`) can be imported directly when running individual
test files (e.g. `python -m unittest tests/v3_yakala_windows_test.py`).
"""
from pathlib import Path
import sys

_TESTS_DIR = str(Path(__file__).resolve().parent)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)
