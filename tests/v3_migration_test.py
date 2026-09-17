"""Synthetic migration/continuity acceptance tests, fixed before implementation."""
import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'template/.claude/scripts'))


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'vault'
        self.root.mkdir()
        self.state = Path(self.temp.name) / 'state'
        self.m = importlib.import_module('beyin_v3_migrate')

    def source(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(text.encode('utf-8'))
        return p

    def test_sources_and_v2_state_preserved_idempotent_cutover(self):
        paths = [self.source('daily/2025-01-01.md', 'Human day\r\n'),
                 self.source('knowledge/idea.md', 'Existing knowledge ölçüm\n'),
                 self.source('Companion/Core.md', 'Existing persona\n'),
                 self.source('.claude/scripts/.state/compile-state.json', '{"last":"2025-01-01"}')]
        before = {p: p.read_bytes() for p in paths}
        first = self.m.migrate_v2(self.root, self.state)
        second = self.m.migrate_v2(self.root, self.state)
        self.assertEqual(first['cutover_at'], second['cutover_at'])
        self.assertTrue(all(p.read_bytes() == value for p, value in before.items()))
        self.assertTrue((self.state / 'v2-migration.json').exists())

    def test_inflight_writer_blocks_without_success_receipt(self):
        self.source('.claude/scripts/.state/flush-example.json', '{"status":"inflight"}')
        with self.assertRaisesRegex(RuntimeError, r'flush-example\.json.*reconcile'):
            self.m.migrate_v2(self.root, self.state)
        self.assertFalse((self.state / 'v2-migration.json').exists())

    def test_legacy_lock_is_guarded_but_excluded_from_inventory(self):
        lock = self.source('.claude/scripts/.state/compile.lock', '')
        state_file = self.source('.claude/scripts/.state/compile-state.json', '{"status":"ok"}')
        with self.m.migration_guard(self.root, self.state) as plan:
            self.assertNotIn(lock.relative_to(self.root).as_posix(), plan['legacy_state'])
            self.assertIn(state_file.relative_to(self.root).as_posix(), plan['legacy_state'])

    def test_legacy_state_symlink_escape_rejected_without_copy(self):
        external = Path(self.temp.name)/'external'
        external.mkdir()
        (external/'flush-private.json').write_text('{}')
        parent = self.root/'.claude/scripts'
        parent.mkdir(parents=True)
        try:
            (parent/'.state').symlink_to(external, target_is_directory=True)
        except OSError:
            self.skipTest('symlink unavailable')
        with self.assertRaisesRegex(RuntimeError, 'symlink'):
            self.m.migrate_v2(self.root, self.state)
        self.assertFalse((self.state/'v2-preserved-state').exists())

    def test_existing_active_legacy_lock_rejected(self):
        lock = self.source('.claude/scripts/.state/compile.lock', '0')
        with self.m._legacy_lock(lock):
            with self.assertRaisesRegex(RuntimeError, 'legacy writer lock'):
                self.m.migrate_v2(self.root, self.state)

    def test_uncut_legacy_runner_prevents_success_watermark(self):
        self.source('.claude/scripts/flush.py', 'print("old writer")\n')
        with self.assertRaisesRegex(RuntimeError, 'runner'):
            self.m.migrate_v2(self.root, self.state)
        self.assertFalse((self.state/'v2-migration.json').exists())

    def test_concurrent_content_edit_blocks_finalize(self):
        p = self.source('Companion/Core.md', 'old')
        with self.m.migration_guard(self.root, self.state) as plan:
            p.write_text('new', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'changed'):
                self.m.finalize_migration(self.root, self.state, plan)
        self.assertEqual(p.read_text(), 'new')

    def test_receipts_project_new_views_without_old_day_recapture(self):
        from beyin_v3_sync import SyncEngine
        day = self.source('daily/2025-01-01.md', 'Human daily stays exact\n')
        old_receipt = self.source('receipts/old.md', 'Historical receipt must not be recaptured')
        self.m.migrate_v2(self.root, self.state)
        source = self.source('notes/example.md', 'Synthetic completed artifact')
        engine = SyncEngine(self.root, self.state)
        engine.receipt('new-event', 'Verified synthetic outcome.', ['notes/example.md'], 'codex')
        engine.sync()
        daily = list((self.root / 'daily/v3').glob('*.md'))
        self.assertEqual(len(daily), 1)
        self.assertEqual(daily[0].read_text().count('Verified synthetic outcome.'), 1)
        self.assertNotIn('Historical receipt', daily[0].read_text())
        self.assertEqual(day.read_bytes(), b'Human daily stays exact\n')
        self.assertEqual(old_receipt.read_text(), 'Historical receipt must not be recaptured')
        self.assertIn('Verified synthetic outcome.', (self.root / 'knowledge/v3/outcomes.md').read_text())

    def test_manual_generated_view_edit_preserved_and_reported(self):
        from beyin_v3_sync import SyncEngine
        self.source('notes/example.md', 'Synthetic source')
        engine = SyncEngine(self.root, self.state)
        engine.receipt('one', 'One outcome.', ['notes/example.md'], 'codex')
        target = self.root / 'knowledge/v3/outcomes.md'
        target.write_text('Manual edit', encoding='utf-8')
        result = engine.sync()
        self.assertEqual(result['status'], 'conflict')
        self.assertEqual(target.read_text(), 'Manual edit')

    def test_companion_private_metadata_excluded(self):
        from beyin_v3_sync import SyncEngine
        self.source('Companion/Core.md', '---\n{"visibility":"private"}\n---\nPRIVATE_PERSONA_CANARY')
        engine = SyncEngine(self.root, self.state)
        engine.sync()
        self.assertTrue(engine.store.retrieve('PRIVATE_PERSONA_CANARY')['abstained'])

    def test_semantic_note_create_preserves_existing_source(self):
        from beyin_v3_sync import SyncEngine
        engine = SyncEngine(self.root, self.state)
        engine.note_create('knowledge/lesson.md', 'Learned synthetic lesson.', {'project': 'demo'})
        original = (self.root/'knowledge/lesson.md').read_bytes()
        with self.assertRaises(ValueError):
            engine.note_create('knowledge/lesson.md', 'Overwrite', {})
        self.assertEqual((self.root/'knowledge/lesson.md').read_bytes(), original)

    def test_receipt_gap_is_only_a_signal_and_closes_on_matching_receipt(self):
        from beyin_v3_sync import SyncEngine
        from beyin_v3_projections import record_checkpoints
        self.source('notes/example.md', 'Synthetic source')
        engine = SyncEngine(self.root, self.state)
        record_checkpoints(engine, [{'event': 'Stop', 'harness': 'codex', 'session': 'synthetic', 'at': 1}])
        engine.sync()
        gaps = json.loads((self.state/'receipt-gaps.json').read_text())
        self.assertEqual(gaps['potential_missing_receipts'], 1)
        self.assertFalse((self.root/'daily/v3').exists())
        engine.receipt('session-outcome', 'Explicit synthetic outcome.', ['notes/example.md'], 'codex', session='synthetic')
        engine.sync()
        self.assertEqual(json.loads((self.state/'receipt-gaps.json').read_text())['potential_missing_receipts'], 0)

    def test_prior_turn_receipt_does_not_cover_next_turn(self):
        from beyin_v3_sync import SyncEngine
        from beyin_v3_projections import record_checkpoints
        import time
        self.source('notes/example.md', 'Synthetic source')
        engine = SyncEngine(self.root, self.state)
        record_checkpoints(engine, [{'event': 'UserPromptSubmit', 'harness': 'codex', 'session': 'same', 'at': time.time()-10}])
        engine.receipt('turn-one', 'First outcome.', ['notes/example.md'], 'codex', session='same')
        record_checkpoints(engine, [{'event': 'UserPromptSubmit', 'harness': 'codex', 'session': 'same', 'at': time.time()+1}, {'event': 'Stop', 'harness': 'codex', 'session': 'same', 'at': time.time()+2}])
        engine.sync()
        self.assertEqual(json.loads((self.state/'receipt-gaps.json').read_text())['potential_missing_receipts'], 1)

if __name__ == '__main__':
    unittest.main()
