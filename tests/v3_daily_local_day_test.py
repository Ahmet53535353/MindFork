#!/usr/bin/env python3
"""daily/v3 is named by the reader's local day while receipt stamps stay UTC (#149); synthetic fixtures only."""
from datetime import timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'template/.claude/scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
_bytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True
try:
    import beyin_v3_projections as projections  # noqa: E402
    import beyin_v3_sync as sync_module  # noqa: E402
finally:
    sys.dont_write_bytecode = _bytecode

PLUS3 = timezone(timedelta(hours=3), 'UTC+3')
LATE_UTC = '2026-09-28T21:30:00+00:00'  # 00:30 on 2026-09-29 at UTC+3


class ReceiptDayTest(unittest.TestCase):
    def test_local_day_follows_zone_and_stamp_is_not_sliced(self):
        self.assertEqual(projections.receipt_day(LATE_UTC, PLUS3), '2026-09-29')
        self.assertEqual(projections.receipt_day(LATE_UTC, timezone.utc), '2026-09-28')
        self.assertEqual(projections.receipt_day('2026-09-28T21:30:00Z', PLUS3), '2026-09-29')
        self.assertEqual(projections.receipt_day('2026-09-28T21:30:00', PLUS3), '2026-09-29')  # naive is UTC
        self.assertEqual(projections.receipt_day('2026-09-29T00:30:00+03:00', timezone.utc), '2026-09-28')

    def test_unreadable_stamp_has_no_day(self):
        for stamp in ('2026-13-45T00:00:00+00:00', '../../evil', '', 5, None):
            self.assertIsNone(projections.receipt_day(stamp, PLUS3), stamp)


class DailyLocalDayProjectionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='beyin-daily-day-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        (self.vault / 'notes').mkdir(parents=True)
        (self.vault / 'notes/task.md').write_text('# Task\n', encoding='utf-8')
        self.engine = sync_module.SyncEngine(self.vault, self.root / 'state')
        self.addCleanup(lambda: getattr(self.engine.store, 'close', lambda: None)())
        self.daily = self.vault / 'daily/v3'

    def zone(self, zone):
        return patch.object(projections, '_local_zone', lambda: zone)

    def receipt_file(self, event_id, created_at, summary):
        metadata = {'kind': 'receipt', 'event_id': event_id, 'harness': 'codex', 'refs': ['notes/task.md'],
                    'visibility': 'internal', 'created_at': created_at}
        receipts = self.vault / 'receipts'
        receipts.mkdir(exist_ok=True)
        (receipts / (sync_module._hash(event_id) + '.md')).write_bytes(
            sync_module.render(metadata, summary + '\n').encode('utf-8'))

    def days(self):
        return sorted(path.name for path in self.daily.glob('*.md'))

    def tracked(self):
        with self.engine.store._connect() as db:
            return sorted(row[0] for row in db.execute('SELECT path FROM receipt_views'))

    def test_file_name_is_the_local_day_the_bridge_calls_today(self):
        self.receipt_file('ev-late', LATE_UTC, 'Late night outcome.')
        with self.zone(PLUS3):
            report = self.engine.sync()
        self.assertEqual(report['conflicts'], [])
        self.assertEqual(self.days(), ['2026-09-29.md'])
        view = (self.daily / '2026-09-29.md').read_text(encoding='utf-8')
        self.assertIn('## ' + LATE_UTC, view)  # the stamp itself stays UTC
        outcomes = (self.vault / 'knowledge/v3/outcomes.md').read_text(encoding='utf-8')
        self.assertIn('- 2026-09-29: Late night outcome.', outcomes)

    def test_untouched_utc_named_view_is_retired_so_no_outcome_is_listed_twice(self):
        self.receipt_file('ev-late', LATE_UTC, 'Late night outcome.')
        self.receipt_file('ev-noon', '2026-09-28T09:00:00+00:00', 'Noon outcome.')
        with self.zone(timezone.utc):  # the view as main named it before #149
            self.assertEqual(self.engine.sync()['conflicts'], [])
        self.assertEqual(self.days(), ['2026-09-28.md'])
        with self.zone(PLUS3):
            report = self.engine.sync()
        self.assertEqual(report['conflicts'], [])
        self.assertEqual(self.days(), ['2026-09-28.md', '2026-09-29.md'])
        self.assertNotIn('Late night outcome.', (self.daily / '2026-09-28.md').read_text(encoding='utf-8'))
        self.assertIn('Late night outcome.', (self.daily / '2026-09-29.md').read_text(encoding='utf-8'))


    def test_day_left_without_outcomes_is_removed_file_and_tracking_row(self):
        self.receipt_file('ev-late', LATE_UTC, 'Late night outcome.')
        with self.zone(timezone.utc):
            self.engine.sync()
        self.assertEqual(self.tracked(), ['daily/v3/2026-09-28.md', 'knowledge/v3/outcomes.md'])
        with self.zone(PLUS3):
            report = self.engine.sync()
        self.assertEqual(report['conflicts'], [])
        self.assertEqual(self.days(), ['2026-09-29.md'])
        self.assertEqual(self.tracked(), ['daily/v3/2026-09-29.md', 'knowledge/v3/outcomes.md'])
        # A view deleted by hand is simply forgotten.
        with self.zone(timezone.utc):
            self.engine.sync()
        (self.daily / '2026-09-28.md').unlink()
        with self.zone(PLUS3):
            self.assertEqual(self.engine.sync()['conflicts'], [])
        self.assertEqual(self.days(), ['2026-09-29.md'])

    def test_edited_stale_view_is_never_removed_and_is_reported(self):
        self.receipt_file('ev-late', LATE_UTC, 'Late night outcome.')
        with self.zone(timezone.utc):
            self.engine.sync()
        stale = self.daily / '2026-09-28.md'
        edited = stale.read_text(encoding='utf-8') + '\nMy own note.\n'
        stale.write_text(edited, encoding='utf-8')
        with self.zone(PLUS3):
            report = self.engine.sync()
        self.assertIn({'source': 'daily/v3/2026-09-28.md',
                       'reason': 'manual receipt view edit preserved; view no longer generated'}, report['conflicts'])
        self.assertEqual(stale.read_text(encoding='utf-8'), edited)
        self.assertTrue((self.daily / '2026-09-29.md').is_file())
        # Moving the note out of the generated folder resolves it; nothing else is touched.
        stale.rename(self.vault / 'notes/kept.md')
        with self.zone(PLUS3):
            self.assertEqual(self.engine.sync()['conflicts'], [])
        self.assertEqual((self.vault / 'notes/kept.md').read_text(encoding='utf-8'), edited)
        self.assertNotIn('daily/v3/2026-09-28.md', self.tracked())

    def test_unreadable_stamp_is_skipped_with_a_warning_not_given_an_invented_day(self):
        self.receipt_file('ev-ok', LATE_UTC, 'Readable.')
        with self.zone(PLUS3):
            self.engine.sync()
        with self.engine.store._connect() as db:  # an older runtime row; receipt files are validated on read
            db.execute('INSERT INTO receipts VALUES (?,?)', ('ev-bad', json.dumps(
                {'event_id': 'ev-bad', 'summary': 'Bad stamp.', 'refs': ['notes/task.md'], 'harness': 'codex',
                 'created_at': '2026-13-45T00:00:00+00:00'})))
        with self.zone(PLUS3):
            report = self.engine.sync()
        self.assertEqual(report['conflicts'], [])
        self.assertEqual(report['status'], 'degraded')
        self.assertIn({'source': 'receipts/' + sync_module._hash('ev-bad') + '.md',
                       'reason': 'unreadable receipt created_at; omitted from daily/v3'}, report['warnings'])
        self.assertEqual(self.days(), ['2026-09-29.md'])
        self.assertNotIn('Bad stamp.', (self.vault / 'knowledge/v3/outcomes.md').read_text(encoding='utf-8'))

    @unittest.skipUnless(hasattr(time, 'tzset'), 'time.tzset is POSIX only')
    def test_system_local_zone_is_used_by_default(self):
        old = os.environ.get('TZ')

        def restore():
            if old is None:
                os.environ.pop('TZ', None)
            else:
                os.environ['TZ'] = old
            time.tzset()
        self.addCleanup(restore)
        os.environ['TZ'] = 'Etc/GMT-3'  # POSIX sign: three hours east of UTC
        time.tzset()
        self.receipt_file('ev-late', LATE_UTC, 'Late night outcome.')
        self.assertEqual(self.engine.sync()['conflicts'], [])
        self.assertEqual(self.days(), ['2026-09-29.md'])


if __name__ == '__main__':
    unittest.main()
