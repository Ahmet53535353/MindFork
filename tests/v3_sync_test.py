#!/usr/bin/env python3
"""Source-authoritative synchronization contract, synthetic local fixtures only."""
import importlib.util
import json
from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'template/.claude/scripts/beyin_v3_sync.py'


def load_module():
    if not MODULE.is_file():
        raise AssertionError('SyncEngine not implemented')
    spec = importlib.util.spec_from_file_location('beyin_v3_sync_test_subject', MODULE)
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


class SourceSyncTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.tmp = tempfile.TemporaryDirectory(prefix='beyin-sync-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'Synthetic Beyin Çalışma'
        self.vault.mkdir()
        self.state = self.root / 'runtime'
        self.engine = self.module.SyncEngine(self.vault, self.state)
        self.addCleanup(lambda: getattr(self.engine.store, 'close', lambda: None)())

    def write(self, name='notes/task.md', body='Nebula calibration awaits owner Synthetic Reviewer.\n', **changes):
        metadata = {'id': 'nebula-task', 'kind': 'task', 'project': 'nebula', 'revision': 1,
                    'status': 'active', 'visibility': 'internal', 'facts': {'owner': 'Synthetic Reviewer'}}
        metadata.update(changes)
        path = self.vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('---\n' + json.dumps(metadata, ensure_ascii=False) + '\n---\n' + body, encoding='utf-8')
        return path

    def records(self, query='Nebula calibration', **kwargs):
        return self.engine.store.retrieve(query, project='nebula', **kwargs)['records']

    def test_add_edit_delete_follow_authoritative_source(self):
        path = self.write()
        result = self.engine.sync()
        self.assertEqual(result['status'], 'succeeded')
        self.assertGreaterEqual(result['indexed'], 1)
        self.assertEqual(self.records()[0]['facts']['owner'], 'Synthetic Reviewer')
        self.write(body='Nebula calibration approved by New Reviewer.\n', revision=2, facts={'owner': 'New Reviewer'})
        self.engine.sync()
        records = self.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['revision'], 2)
        self.assertEqual(records[0]['facts']['owner'], 'New Reviewer')
        self.assertNotIn('Synthetic Reviewer', records[0]['text'])
        path.unlink()
        deleted = self.engine.sync()
        self.assertGreaterEqual(deleted['deleted'], 1)
        self.assertEqual(self.records(), [])

    def test_duplicate_source_id_quarantined_without_winner(self):
        self.write()
        self.engine.sync()
        self.write('notes/conflicting.md', body='Nebula calibration has different owner.\n')
        report = self.engine.sync()
        self.assertTrue(report['conflicts'])
        self.assertEqual(self.records(), [])
        self.assertTrue((self.vault / 'notes/task.md').exists())
        self.assertTrue((self.vault / 'notes/conflicting.md').exists())

    def test_source_rename_updates_citation_without_duplicate(self):
        path = self.write()
        self.engine.sync()
        destination = path.with_name('renamed.md')
        path.rename(destination)
        self.engine.sync()
        records = self.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['id'], 'nebula-task')
        self.assertEqual(records[0]['source'], 'notes/renamed.md')

    def test_plain_markdown_full_thread_body_preserved(self):
        path = self.vault / 'Threads.md'
        body = '# Threads\n## Active\n### Thread: Spectroscope\n**Status:** waiting\nSpectroscope decision belongs to Synthetic Reviewer.\nNext action: inspect violet calibration sample.\n'
        path.write_text(body, encoding='utf-8')
        self.engine.sync()
        response = self.engine.store.retrieve('Spectroscope decision reviewer')
        self.assertEqual(len(response['records']), 1)
        self.assertIn('Next action: inspect violet calibration sample.', response['records'][0]['text'])
        self.assertIn('decision belongs to Synthetic Reviewer.', response['records'][0]['text'])
        self.assertEqual(response['records'][0]['source'], 'Threads.md')

    def test_public_boundary_excludes_private_and_untrusted_source(self):
        self.write('notes/public.md', id='visible', visibility='public')
        self.write('notes/private.md', id='hidden', visibility='private', body='Nebula calibration SYNTHETIC_PRIVATE_CANARY\n')
        self.write('notes/untrusted.md', id='untrusted', kind='untrusted')
        self.engine.sync()
        response = self.engine.store.retrieve('Nebula calibration', project='nebula', audience='public')
        self.assertEqual([r['id'] for r in response['records']], ['visible'])
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(response))

    def test_receipt_markdown_idempotent_and_collision_rejected(self):
        self.write()
        self.engine.sync()
        first = self.engine.receipt('synthetic-event', 'Nebula reviewed.', ['notes/task.md'], 'codex')
        second = self.engine.receipt('synthetic-event', 'Nebula reviewed.', ['notes/task.md'], 'claude')
        self.assertEqual(first, second)
        self.assertEqual(first['status'], 'succeeded')
        source = self.vault / first['source']
        self.assertTrue(source.is_file())
        self.assertIn('Nebula reviewed.', source.read_text(encoding='utf-8'))
        original = source.read_bytes()
        with self.assertRaises(ValueError):
            self.engine.receipt('synthetic-event', 'Different summary.', ['notes/task.md'], 'codex')
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(len(list((self.vault / 'receipts').glob('*.md'))), 1)
        self.engine.sync()
        self.assertFalse(any(r.get('kind') == 'receipt' for r in self.records('Nebula reviewed')))

    def test_receipt_manually_mutated_source_never_overwritten(self):
        self.write()
        self.engine.sync()
        receipt = self.engine.receipt('edited-event', 'Nebula reviewed.', ['notes/task.md'], 'codex')
        source = self.vault / receipt['source']
        source.write_text('User synthetic edit must survive.\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.engine.receipt('edited-event', 'Nebula reviewed.', ['notes/task.md'], 'codex')
        self.assertEqual(source.read_text(encoding='utf-8'), 'User synthetic edit must survive.\n')

    def test_task_update_preserves_body_and_rejects_stale_revision(self):
        body = 'Nebula calibration.\n\n- Keep this exact task prose.\n  Unicode: ölçüm 🔭\n'
        path = self.write(body=body)
        self.engine.sync()
        updated = self.engine.update_task('nebula-task', 1, {'status': 'waiting'})
        self.assertEqual(updated['revision'], 2)
        self.assertEqual(updated['status'], 'waiting')
        self.assertEqual(path.read_text(encoding='utf-8').split('\n---\n', 1)[1], body)
        saved = path.read_bytes()
        with self.assertRaises(ValueError):
            self.engine.update_task('nebula-task', 1, {'status': 'done'})
        self.assertEqual(path.read_bytes(), saved)
        self.engine.sync()
        self.assertEqual(self.records()[0]['status'], 'waiting')

    def test_manual_edit_without_revision_bump_invalidates_old_expected_revision(self):
        self.write()
        self.engine.sync()
        self.assertEqual(self.records()[0]['revision'], 1)
        # Human editor changes authoritative content but leaves frontmatter revision 1.
        self.write(body='Nebula calibration manually changed by source author.\n', status='waiting')
        self.engine.sync()
        effective = self.records()[0]['revision']
        self.assertEqual(effective, 2)
        self.engine.sync()
        self.assertEqual(self.records()[0]['revision'], effective)
        with self.assertRaises(ValueError):
            self.engine.update_task('nebula-task', 1, {'status': 'done'})
        updated = self.engine.update_task('nebula-task', effective, {'status': 'done'})
        self.assertEqual(updated['revision'], 3)
        self.engine.sync()
        self.assertEqual(self.records()[0]['revision'], 3)

    def test_unsupported_metadata_reports_degraded_not_succeeded(self):
        source = self.vault / 'unsupported.md'
        source.write_text('---\nid: unsupported\nfacts:\n  owner: Synthetic Reviewer\n---\nNebula calibration metadata fixture.\n', encoding='utf-8')
        report = self.engine.sync()
        self.assertTrue(report['warnings'])
        self.assertEqual(report['status'], 'degraded')
        self.assertEqual(self.records(), [])

    def test_receipt_has_immutable_iso_created_at(self):
        self.write()
        self.engine.sync()
        receipt = self.engine.receipt('dated-receipt', 'Synthetic dated evidence.', ['notes/task.md'], 'codex')
        path = self.vault / receipt['source']
        original = path.read_bytes()
        frontmatter = path.read_text(encoding='utf-8').split('---', 2)[1]
        metadata = json.loads(frontmatter)
        self.assertIn('created_at', metadata)
        timestamp = datetime.fromisoformat(metadata['created_at'].replace('Z', '+00:00'))
        self.assertIsNotNone(timestamp.tzinfo)
        self.assertEqual(receipt, self.engine.receipt('dated-receipt', 'Synthetic dated evidence.', ['notes/task.md'], 'claude'))
        self.assertEqual(path.read_bytes(), original)

    def test_no_query_snapshot_preserves_visibility_status_and_budget(self):
        self.write('notes/active.md', id='active', status='active', visibility='public')
        self.write('notes/waiting.md', id='waiting', status='waiting')
        self.write('notes/done.md', id='done', status='done')
        self.write('notes/private.md', id='private', visibility='private')
        self.write('notes/untrusted.md', id='untrusted', kind='untrusted')
        self.engine.sync()
        response = self.engine.store.snapshot_context(audience='internal', budget_chars=8000, limit=5)
        self.assertEqual({r['id'] for r in response['records']}, {'active', 'waiting'})
        self.assertLessEqual(response['used_chars'], 8000)
        public = self.engine.store.snapshot_context(audience='public', budget_chars=8000, limit=5)
        self.assertEqual([r['id'] for r in public['records']], ['active'])

    def test_snapshot_includes_plain_notes_and_statusless_facts(self):
        plain = self.vault / 'observatory.md'
        plain.write_text('# Synthetic observatory note\nNebula observatory uses violet calibration.\n', encoding='utf-8')
        fact = self.vault / 'fact.md'
        fact.write_text('---\n' + json.dumps({'id': 'statusless-fact', 'kind': 'fact', 'project': 'nebula', 'visibility': 'internal'}) +
                        '\n---\nNebula spectroscope owner is Synthetic Reviewer.\n', encoding='utf-8')
        self.write('notes/done.md', id='done-task', status='done')
        self.engine.sync()
        snapshot = self.engine.store.snapshot_context(audience='internal', budget_chars=8000, limit=5)
        self.assertEqual({r['source'] for r in snapshot['records']}, {'observatory.md', 'fact.md'})
        self.assertNotIn('done-task', [r['id'] for r in snapshot['records']])
        self.assertIn('violet calibration', json.dumps(snapshot))
        self.assertIn('Synthetic Reviewer', json.dumps(snapshot))

    def test_source_replace_failure_recovers_consistently(self):
        path = self.write()
        self.engine.sync()
        original = path.read_bytes()
        real_replace = os.replace
        def fail_source(src, dst, *args, **kwargs):
            if Path(dst).resolve() == path.resolve():
                raise OSError('Synthetic source replace failure')
            return real_replace(src, dst, *args, **kwargs)
        with patch.object(self.module.os, 'replace', side_effect=fail_source):
            with self.assertRaises(OSError):
                self.engine.update_task('nebula-task', 1, {'status': 'waiting'})
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.records()[0]['revision'], 1)
        getattr(self.engine.store, 'close', lambda: None)()
        self.engine = self.module.SyncEngine(self.vault, self.state)
        self.engine.sync()
        recovered = self.records()[0]
        self.assertEqual(recovered['revision'], 2)
        self.assertEqual(recovered['status'], 'waiting')
        self.engine.sync()
        self.assertEqual(self.records()[0]['revision'], 2)

    def test_recovery_does_not_overwrite_intervening_manual_change(self):
        path = self.write()
        self.engine.sync()
        real_replace = os.replace
        def fail_source(src, dst, *args, **kwargs):
            if Path(dst).resolve() == path.resolve():
                raise OSError('Synthetic source replace failure')
            return real_replace(src, dst, *args, **kwargs)
        with patch.object(self.module.os, 'replace', side_effect=fail_source):
            with self.assertRaises(OSError):
                self.engine.update_task('nebula-task', 1, {'status': 'waiting'})
        self.write(body='Nebula calibration manual source revision wins.\n', revision=2, status='done')
        manual = path.read_bytes()
        report = self.engine.sync()
        self.assertTrue(report['conflicts'])
        self.assertEqual(path.read_bytes(), manual)
        self.assertNotEqual(self.records()[0]['status'], 'waiting')


if __name__ == '__main__':
    unittest.main()
