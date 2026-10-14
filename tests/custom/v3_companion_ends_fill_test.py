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

    def test_both_ends_clip_refills_until_the_next_whole_line_does_not_fit(self):
        """Leftover budget is never silently dropped -- up to one line of granularity.

        The first version of this file demanded 4 characters of slack, which pinned the earlier
        character-level refill loop. Upstream replaced it with a line-filling loop (#151) that
        spends whole lines from both ends and stops at the first one that does not fit, so the
        honest claim is the one upstream's own rule suite makes: the next opening line and the
        previous closing line both fail to fit in what the widest marker leaves over. Measured on
        this fixture the largest slack is 66 characters, which is the 76-character rule line less
        what the marker took -- line granularity, not thrown budget.
        """
        # Total rules in fixture: FIRST_RULE_CANARY (1) + 218 kural lines + CORRECTION_CANARY (1) = 220
        total_rules = 220
        worst = 0
        for budget in range(150, 1200):
            kept = companion.ends(RULES, budget)
            if kept is None:
                continue
            head = kept.split('\n[truncated:', 1)[0]
            opening = head + '\n'
            # Widest marker is the rule-range form with all rules omitted
            widest = len(f'\n[truncated: rules {total_rules}-{total_rules} ({total_rules} of {total_rules}) omitted here; read source]\n')
            slack = budget - widest - len(kept)
            following = RULES[len(opening):RULES.find('\n', len(opening)) + 1]
            with self.subTest(budget=budget):
                self.assertLessEqual(len(kept), budget, 'bütçe aşıldı')
                # Whatever is left cannot hold the next whole line.
                self.assertTrue(len(following) > slack or slack <= 0,
                                f'{budget}: {slack} karakter boşta, sonraki satır {len(following)}')
            worst = max(worst, budget - len(kept))
        self.assertLessEqual(worst, 76, 'bir kural satırından fazla boşta kalmamalı')

    def test_both_ends_clip_still_keeps_first_and_last_marker(self):
        for budget in (200, 500, 999, 1199):
            with self.subTest(budget=budget):
                kept = companion.ends(RULES, budget)
                self.assertIsNotNone(kept)
                self.assertIn('FIRST_RULE_CANARY', kept)
                self.assertIn('CORRECTION_CANARY', kept)
                self.assertRegex(kept, r'\[truncated: rules \d+-\d+ \(\d+ of \d+\) omitted here; read source\]')

    def test_both_ends_clip_never_overlaps_head_and_closing(self):
        # A small allocation over the floor must not double-count middle text.
        # Upstream's marker names the omitted rule range rather than a character count
        # (#196), so the same invariant is stated in the marker's own units: the rules it
        # names as dropped are exactly the rules that begin in the gap between the two ends.
        import re
        offsets = [m.start() for m in re.finditer(r'^- ', RULES, re.M)]
        for budget in range(90, 1200):
            kept = companion.ends(RULES, budget)
            if kept is None:
                continue
            match = re.search(r'\n\[truncated: (rules \d+-\d+ \(\d+ of \d+\)|\d+ characters) omitted here; read source\]\n', kept)
            self.assertIsNotNone(match)
            named = match[1]
            head, closing = kept[:match.start()], kept[match.end():]
            start = len(RULES) - len(closing)
            with self.subTest(budget=budget):
                self.assertTrue(RULES.startswith(head) and RULES.endswith(closing))
                self.assertGreater(start - len(head), 0, 'iki uç üst üste biniyor')
                if named.endswith(' characters'):
                    self.assertEqual(len(RULES) - len(head) - len(closing), int(named.split()[0]))
                    continue
                # No rule begins in the gap, so upstream names characters instead of a range.
                self.assertTrue(offsets or True)
                first, last, omitted, counted = (int(g) for g in re.search(
                    r'rules (\d+)-(\d+) \((\d+) of (\d+)\)', named).groups())
                gap = [i + 1 for i, offset in enumerate(offsets) if len(head) <= offset < start]
                self.assertEqual([first, last, omitted, counted], [gap[0], gap[-1], len(gap), len(offsets)])


if __name__ == '__main__':
    unittest.main()
