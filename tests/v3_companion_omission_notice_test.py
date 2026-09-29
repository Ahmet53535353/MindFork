"""A truncated rule set names what it left out, not only how much.

`ends()` keeps the opening and the closing and drops the middle, but the marker only counted
characters. A rule set is a list of dated corrections the agent is told to obey, so "717
characters omitted here" leaves the agent unable to tell whether a rule is missing at all --
it cannot tell whether to go read the source. In a live run this is the worst kind of loss:
a whole rule disappears and nothing in the context says so.

The marker therefore counts what was dropped. The budget is unchanged and the same two ends
are kept, so this is visibility only: what was already lost is still lost, but now it is
named. Ranking or reordering rules is a separate decision, deliberately not taken here.
"""
import importlib.util
from pathlib import Path
import os
import sys
import unittest

ROOT = Path(os.environ.get('BEYIN_TEST_REPO', Path(__file__).resolve().parents[1]))


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


companion = load('beyin_v3_omission_companion', 'template/.claude/scripts/beyin_v3_companion.py')


def rule_set(count, body='ayrıntılı bir çalışma kuralının tam metni burada durur ve devam eder. ' * 12):
    return ''.join(f'## 2026-09-{day:02d} · Kural {day}\n- Kural: {body}\n' for day in range(1, count + 1))


class OmissionNoticeTest(unittest.TestCase):
    """The marker names the sections it dropped; the budget and the kept ends do not move."""

    def setUp(self):
        self.original = os.environ.get('TZ')
        self.addCleanup(self.restore)

    def restore(self):
        if self.original is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = self.original

    def test_the_marker_counts_the_dropped_sections(self):
        """Six rules, three survive; the marker has to say so in a form an agent can act on."""
        text = rule_set(6)
        out = companion.ends(text, 1660)
        kept = [line for line in out.splitlines() if line.startswith('## ')]
        omitted = 6 - len(kept)
        self.assertGreater(omitted, 0, 'bütçe sığdı, kırpma olmadı: test ölçüm yapmıyor')
        self.assertRegex(out, r'\[truncated: \d+ characters, \d+ of 6 sections omitted',
                         'işaret düşen bölüm sayısını söylemiyor')

    def test_a_text_without_sections_still_reports_characters_only(self):
        """Sources and receipts have no `##` structure; inventing a count for them would be a lie."""
        plain = 'bir kaynak dosyasının düz metni\n' * 200
        out = companion.ends(plain, 800)
        self.assertIn('[truncated:', out)
        self.assertNotIn('sections omitted', out)
        self.assertNotIn('0 of 0', out)

    def test_the_budget_and_the_two_ends_are_unchanged(self):
        """Visibility only: a richer marker must not push the output over budget.

        Both ends survive only where the budget is wide enough for them; at 900 a single rule
        already fills the allocation and the closing is dropped today. That is the existing
        behaviour and this change is not allowed to move it in either direction.
        """
        for budget, both_ends in ((1660, True), (3000, True), (5000, True), (900, False)):
            with self.subTest(budget=budget):
                text = rule_set(8)
                out = companion.ends(text, budget)
                self.assertLessEqual(len(out), budget, 'işaret bütçeyi aştı')
                self.assertIn('## 2026-09-01 · Kural 1', out, 'açılış korunmalı')
                if both_ends:
                    self.assertIn('## 2026-09-08 · Kural 8', out, 'kapanış korunmalı')

    def test_a_text_that_fits_is_never_reported_as_truncated(self):
        """A false alarm is worse than no notice: it sends the agent to read a source it has.

        `clip()` guards on length before delegating, but `ends()` is a public function and the
        filler loop in it can grow a closing part past the original text, so a source that fits
        the budget came back carrying a marker and with a zero omission count.
        """
        text = rule_set(2, body='kısa bir kural metni. ')
        self.assertLess(len(text), 1660)
        out = companion.ends(text, 1660)
        self.assertNotIn('[truncated:', out, 'bütçeye sığan metin kırpılmış gibi bildirildi')
        self.assertEqual(out, text, 'bütçeye sığan metin değiştirilmemeli')

    def test_the_count_never_claims_more_than_the_text_holds(self):
        """A stale count from the slack-refill loop would be worse than no count at all."""
        for count in (2, 5, 12, 40):
            with self.subTest(count=count):
                text = rule_set(count)
                out = companion.ends(text, 1200)
                import re
                match = re.search(r'(\d+) of (\d+) sections omitted', out)
                if not match:
                    continue
                dropped, total = int(match.group(1)), int(match.group(2))
                kept = len([line for line in out.splitlines() if line.startswith('## ')])
                self.assertEqual(total, count, 'toplam bölüm sayısı kaynakla uyuşmuyor')
                self.assertEqual(dropped + kept, count,
                                 f'{dropped} düşen + {kept} görünen = {count} olmalı')
                self.assertGreaterEqual(dropped, 1, 'kırpma varken 0 düşen denemez')


if __name__ == '__main__':
    unittest.main()
