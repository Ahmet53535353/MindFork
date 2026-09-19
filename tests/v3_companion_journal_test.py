"""Journal excerpt selection: the newest entry wins in both writing directions."""
import importlib.util
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(os.environ.get('BEYIN_TEST_REPO', Path(__file__).resolve().parents[1]))
spec = importlib.util.spec_from_file_location('beyin_v3_companion_excerpt',
                                              ROOT / 'template/.claude/scripts/beyin_v3_companion.py')
companion = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = companion
spec.loader.exec_module(companion)

LATEST = '## 2026-09-18 (öğlen{time})\nLATEST_ENTRY: bugünün son notu.\n'
EARLIER = '## 2026-09-18 (sabah{time})\nOLDER_ENTRY: bugünün ilk notu.\n'
ANCIENT = '## 2026-08-01\nANCIENT_ENTRY: eski not.\n'


def journal(newest_first, times):
    today = [LATEST.format(time=', 14:00' if times else ''), EARLIER.format(time=', 09:00' if times else '')]
    entries = today + [ANCIENT] if newest_first else [ANCIENT] + today[::-1]
    return '# Journal\n' + ''.join(entries)


class JournalExcerptTest(unittest.TestCase):
    def test_latest_same_date_entry_wins_in_every_writing_direction(self):
        for newest_first in (True, False):
            for times in (True, False):
                with self.subTest(newest_first=newest_first, times=times):
                    excerpt = companion.excerpt('Journal.md', journal(newest_first, times))
                    self.assertIn('LATEST_ENTRY', excerpt)
                    self.assertNotIn('OLDER_ENTRY', excerpt)
                    self.assertNotIn('ANCIENT_ENTRY', excerpt)

    def test_distinct_dates_and_undated_journals_are_unchanged(self):
        newest_first = '# Journal\n## 2026-09-17\nLATEST_ENTRY\n## 2020-01-01\nANCIENT_ENTRY\n'
        appended = '# Journal\n## 2020-01-01\nANCIENT_ENTRY\n## 2026-09-17\nLATEST_ENTRY\n'
        undated = '# Journal\n## İlk gözlem\nANCIENT_ENTRY\n## Sonraki gözlem\nLATEST_ENTRY\n'
        for text in (newest_first, appended, undated):
            excerpt = companion.excerpt('Journal.md', text)
            self.assertIn('LATEST_ENTRY', excerpt)
            self.assertNotIn('ANCIENT_ENTRY', excerpt)

    def test_other_sources_are_returned_untouched(self):
        self.assertEqual(companion.excerpt('Core.md', '# Kimlik\n## 2026-09-18\nx\n'), '# Kimlik\n## 2026-09-18\nx\n')


if __name__ == '__main__':
    unittest.main()
