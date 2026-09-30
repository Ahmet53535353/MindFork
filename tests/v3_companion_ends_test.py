"""Both-ends clipping of a rule set: whole lines only, and the budget is used (#151)."""
from pathlib import Path
import random
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))
from beyin_v3_companion import clip, ends

MARKER = re.compile(r'\n\[truncated: (\d+) characters omitted here; read source\]\n')


def split(text, result):
    match = MARKER.search(result)
    head, closing = result[:match.start()], result[match.end():]
    return head, closing, int(match[1])


class EndsTest(unittest.TestCase):
    def rules(self, seed, count, widths):
        rng = random.Random(seed)
        return '# Kurallar\n' + ''.join(f'- kural {i}: ' + 'x' * rng.randint(0, rng.choice(widths)) + '\n'
                                        for i in range(count))

    def test_text_that_fits_is_returned_untouched(self):
        text = self.rules(1, 5, (40,))
        self.assertEqual(ends(text, len(text)), text)
        self.assertEqual(ends(text, len(text) + 500), text)

    def test_ends_keep_whole_lines_and_leave_no_whole_line_unused(self):
        cases = 0
        for seed in range(400):
            text = self.rules(seed, 10 + seed % 90, (20, 60, 200))
            budget = random.Random(seed).randint(200, len(text) - 1)
            result = ends(text, budget)
            if result is None:
                continue
            cases += 1
            with self.subTest(seed=seed, budget=budget):
                self.assertLessEqual(len(result), budget)
                head, closing, omitted = split(text, result)
                self.assertTrue(text.startswith(head))
                self.assertTrue(text.endswith(closing))
                self.assertEqual(omitted, len(text) - len(head) - len(closing))
                self.assertGreater(omitted, 0)
                # Whole lines, unless one line alone is longer than its end's share.
                self.assertTrue(head.endswith('\n') or '\n' not in head)
                self.assertTrue(text[:len(text) - len(closing)].endswith('\n') or '\n' not in closing[:-1])
                # Maximal: neither the next opening line nor the previous closing line fits
                # in what the widest possible marker leaves.
                widest = len(f'\n[truncated: {len(text)} characters omitted here; read source]\n')
                slack = budget - widest - len(head) - len(closing)
                start = len(text) - len(closing)
                following = text[len(head):text.find('\n', len(head)) + 1]
                previous = text[text.rfind('\n', 0, start - 1) + 1:start]
                self.assertTrue(len(following) >= start - len(head) or len(following) > slack, following)
                self.assertTrue(len(previous) >= start - len(head) or len(previous) > slack, previous)
        self.assertGreater(cases, 300)

    def test_short_lines_fill_the_budget(self):
        text = ''.join(f'- kural {i:03d}: kisa bir kural\n' for i in range(300))
        for budget in (500, 1000, 2000, 3000, 5000):
            with self.subTest(budget=budget):
                result = clip(text, budget, both=True)
                self.assertLessEqual(len(result), budget)
                self.assertGreaterEqual(len(result), budget - 2 * 26)
                self.assertIn('kural 000', result)
                self.assertIn('kural 299', result)


if __name__ == '__main__':
    unittest.main()
