"""A receipt's daily index is named in the machine's day, and an old day leaves nothing behind.

`beyin_v3_projections.py` used to slice the day straight off the stored UTC stamp
(`event['created_at'][:10]`) while the human daily log (`beyin_v3_sessionlog._day`) follows the
machine. At +03:00 the first hours of a day landed under yesterday's name in one file and today's
in the other, so one working day was split across two files. Both live in `daily/` and both answer
"what happened today", so they must read the same clock: the machine's. The consolidation window
(`beyin_v3_dream._now`) stays UTC on purpose -- it is a batch boundary, not a human day, and
`tests/v3_local_utc_day_divergence_test.py` pins that split.

The writer is a full recomputation: every sync regroups every receipt and rewrites the desired
paths. It never deleted a path it stopped wanting, so renaming the day would have left the old
file in place with the same receipts in it -- silently, because its hash still matched the row in
`receipt_views`. That is the second half of this test.
"""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

ROOT = Path(os.environ.get('BEYIN_TEST_REPO', Path(__file__).resolve().parents[1]))
MODULE = ROOT / 'template/.claude/scripts/beyin_v3_sync.py'
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))
import beyin_v3_projections as projections

# 21:30 UTC is 00:30 the next day at +03:00, inside the window where the two clocks disagree.
STAMP = '2026-09-28T21:30:00+00:00'
EAST_DAY = '2026-09-29'
UTC_DAY = '2026-09-28'


def load_module():
    spec = importlib.util.spec_from_file_location('beyin_v3_sync_projection_day_subject', MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    scripts = str(MODULE.parent)
    sys.path.insert(0, scripts)
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old
        sys.path.remove(scripts)
    return module


class ProjectionDayTest(unittest.TestCase):
    """The index names the human day, and a day that no longer wants a file does not keep one."""

    def setUp(self):
        self.original = os.environ.get('TZ')
        self.addCleanup(self.restore)
        self.module = load_module()
        self.tmp = tempfile.TemporaryDirectory(prefix='beyin-projection-day-')
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name) / 'Vault'
        self.vault.mkdir()
        self.engine = self.module.SyncEngine(self.vault, Path(self.tmp.name) / 'state')
        self.addCleanup(lambda: getattr(self.engine.store, 'close', lambda: None)())
        self.source = self.vault / 'notes/source.md'
        self.source.parent.mkdir(parents=True, exist_ok=True)
        self.source.write_text('---\n{"kind": "note", "visibility": "internal"}\n---\nKaynak.\n', encoding='utf-8')

    def restore(self):
        if self.original is None:
            os.environ.pop('TZ', None)
        else:
            os.environ['TZ'] = self.original
        time.tzset()

    def in_zone(self, zone):
        os.environ['TZ'] = zone
        time.tzset()

    def record(self, ident, stamp):
        """One receipt at a fixed stamp; receipt() itself always stamps the wall clock."""
        with self.engine.store._connect() as db:
            db.execute('INSERT OR REPLACE INTO receipts VALUES (?,?)', (ident, json.dumps({
                'event_id': ident, 'summary': f'{ident} sonucu.', 'refs': ['notes/source.md'],
                'harness': 'codex', 'created_at': stamp,
            })))

    def daily(self):
        return sorted(p.name for p in (self.vault / 'daily' / 'v3').glob('*.md'))

    def test_the_index_names_the_machine_day_not_the_utc_day(self):
        self.in_zone('Etc/GMT-3')
        self.record('gece', STAMP)
        self.engine.sync()
        self.assertEqual(self.daily(), [f'{EAST_DAY}.md'],
                         'günlük dizin UTC gününü değil insanın gününü adlandırmalı')

    def test_under_utc_both_clocks_agree_so_this_stays_a_utc_only_finding(self):
        self.in_zone('UTC')
        self.record('gece', STAMP)
        self.engine.sync()
        self.assertEqual(self.daily(), [f'{UTC_DAY}.md'])

    def test_a_day_that_stops_wanting_a_file_does_not_keep_a_stale_one(self):
        """The regression the rename would otherwise ship: the same receipt in two files."""
        self.in_zone('Etc/GMT-3')
        self.record('gece', STAMP)
        self.engine.sync()
        # The file is left exactly as the engine wrote it; only the receipt's day moves.
        with self.engine.store._connect() as db:
            db.execute("UPDATE receipts SET payload=replace(payload, ?, ?)",
                       (STAMP, '2026-09-28T12:00:00+00:00'))
        self.engine.sync()
        self.assertEqual(self.daily(), [f'{UTC_DAY}.md'], 'gün değişti ama eski dosya öksüz kaldı')

    def test_an_unreadable_stamp_is_skipped_not_fatal(self):
        """Slicing `created_at[:10]` read past a corrupt value and invented a day for it."""
        self.in_zone('Etc/GMT-3')
        self.record('bozuk', '2026-13-45T00:00:00+00:00')
        self.record('gece', STAMP)
        result = self.engine.sync()
        self.assertNotEqual(result['status'], 'conflict')
        self.assertEqual(self.daily(), [f'{EAST_DAY}.md'], 'bozuk damga uydurma bir gün üretmemeli')
        self.assertIsNone(projections.receipt_day('2026-13-45T00:00:00+00:00'))
        self.assertIsNone(projections.receipt_day(None))

    def test_a_hand_edited_view_is_never_deleted(self):
        self.in_zone('Etc/GMT-3')
        self.record('gece', STAMP)
        self.engine.sync()
        edited = self.vault / 'daily' / 'v3' / f'{EAST_DAY}.md'
        edited.write_text('# Elle yazildi\n', encoding='utf-8')
        with self.engine.store._connect() as db:
            db.execute("UPDATE receipts SET payload=replace(payload, ?, ?)",
                       (STAMP, '2026-09-28T12:00:00+00:00'))
        result = self.engine.sync()
        self.assertTrue(edited.exists(), 'insan düzenlemesi olan görünüm silinmemeli')
        self.assertIn('manual receipt view edit preserved', json.dumps(result))
        self.assertEqual(edited.read_text(encoding='utf-8'), '# Elle yazildi\n')


if __name__ == '__main__':
    unittest.main()
