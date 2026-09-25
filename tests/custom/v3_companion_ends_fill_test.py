#!/usr/bin/env python3
"""Both-ends clipping fills its allocation: leftover budget is never silently dropped."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(os.environ.get('BEYIN_TEST_REPO', Path(__file__).resolve().parents[2]))


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


companion = load('beyin_v3_ends_fill_companion', 'template/.claude/scripts/beyin_v3_companion.py')

RULES = ('# Kurallar\n- FIRST_RULE_CANARY: her oturumda geçerli temel kural.\n' +
         ''.join(f'- kural {i}: ayrıntılı bir çalışma kuralının tam metni burada durur.\n' for i in range(2, 220)) +
         '- CORRECTION_CANARY: gereksiz övgü kullanma.\n')


class EndsFillTest(unittest.TestCase):
    def test_both_ends_clip_never_exceeds_budget(self):
        for budget in range(80, 1200):
            with self.subTest(budget=budget):
                kept = companion.ends(RULES, budget)
                if kept is None:
                    continue
                self.assertLessEqual(len(kept), budget)

    def test_both_ends_clip_keeps_allocation_within_a_few_characters_of_slack(self):
        # The leftover of the line-boundary cut is refilled from the middle; only
        # marker-length digits may cost characters, or the water-filled budget
        # is thrown away.
        worst = 0
        for budget in range(150, 1200):
            kept = companion.ends(RULES, budget)
            if kept is None:
                continue
            worst = max(worst, budget - len(kept))
        self.assertLessEqual(worst, 4)

    def test_both_ends_clip_still_keeps_first_and_last_marker(self):
        for budget in (200, 500, 999, 1199):
            with self.subTest(budget=budget):
                kept = companion.ends(RULES, budget)
                self.assertIsNotNone(kept)
                self.assertIn('FIRST_RULE_CANARY', kept)
                self.assertIn('CORRECTION_CANARY', kept)
                self.assertRegex(kept, r'\[truncated: \d+ characters omitted here; read source\]')

    def test_both_ends_clip_never_overlaps_head_and_closing(self):
        # A small allocation over the floor must not double-count middle text.
        for budget in range(90, 1200):
            kept = companion.ends(RULES, budget)
            if kept is None:
                continue
            import re
            match = re.search(r'\n\[truncated: (\d+) characters omitted here; read source\]\n', kept)
            self.assertIsNotNone(match)
            omitted = int(match[1])
            self.assertGreaterEqual(omitted, 0)
            rebuilt_head = kept[:match.start()]
            rebuilt_closing = kept[match.end():]
            self.assertEqual(len(RULES) - len(rebuilt_head) - len(rebuilt_closing), omitted)


if __name__ == '__main__':
    unittest.main()
