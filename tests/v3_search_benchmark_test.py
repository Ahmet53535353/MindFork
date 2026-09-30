#!/usr/bin/env python3
"""CI discovery contract for V3 search benchmark (#94)."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from v3_search_benchmark import SearchBenchmarkTest

if __name__ == "__main__":
    unittest.main()
