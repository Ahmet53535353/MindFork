#!/usr/bin/env python3
"""Tests for issue #323: receipt projection conflict resilience, view recovery, and context preservation."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'template/.claude/scripts'
sys.path.insert(0, str(SCRIPTS))
from beyin_v3_sync import SyncEngine
from beyin_v3_projections import is_receipt_view_conflict


class ReceiptProjectionConflictTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='beyin-proj-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.state = self.root / 'state'
        (self.vault / 'notes').mkdir(parents=True)
        (self.vault / 'notes/canary.md').write_text(
            '---\nkind: fact\nvisibility: internal\n---\n# Nebula memory canary\nNebula memory canary code is NC-7319.\n',
            encoding='utf-8',
        )

    def _invoke_hook(self, vault, state, prompt='What is the Nebula memory canary code?'):
        env = {k: v for k, v in os.environ.items() if not k.startswith('BEYIN_')}
        env.update(BEYIN_UPDATES_OFF='1', PYTHONDONTWRITEBYTECODE='1')
        payload = {
            'hook_event_name': 'UserPromptSubmit',
            'session_id': 'isolated-session',
            'event_id': 'isolated-prompt',
            'cwd': str(vault),
            'prompt': prompt,
        }
        return subprocess.run(
            [sys.executable, str(SCRIPTS / 'beyin_v3_hook.py'), '--vault', str(vault), '--state', str(state), '--harness', 'codex'],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            env=env,
            timeout=20,
        )

    def test_clean_control(self):
        """Clean control: canary note indexed, seed and second receipts succeed, hook contains canary."""
        engine = SyncEngine(self.vault, self.state)
        sync1 = engine.sync()
        self.assertEqual(sync1['status'], 'succeeded')

        first = engine.receipt('seed', 'Synthetic initial result', ['notes/canary.md'], 'codex', 'isolated-session')
        self.assertEqual(first['status'], 'succeeded')

        second = engine.receipt('second', 'Synthetic second result', ['notes/canary.md'], 'codex', 'isolated-session')
        self.assertEqual(second['status'], 'succeeded')

        hook = self._invoke_hook(self.vault, self.state)
        self.assertEqual(hook.returncode, 0)
        self.assertIn('NC-7319', hook.stdout)
        pending = list((self.state / 'hook-queue').glob('*.json'))
        self.assertEqual(len(pending), 0)

    def test_manual_edit_does_not_block_notes_or_subsequent_receipt(self):
        """Manual edit to outcomes.md is preserved, does not block canary from hook context or second receipt."""
        engine = SyncEngine(self.vault, self.state)
        engine.sync()
        first = engine.receipt('seed', 'Synthetic initial result', ['notes/canary.md'], 'codex', 'isolated-session')
        self.assertEqual(first['status'], 'succeeded')

        view = self.vault / 'knowledge/v3/outcomes.md'
        self.assertTrue(view.exists())
        with view.open('a', encoding='utf-8') as out:
            out.write('\nSynthetic manual annotation to preserve.\n')
        before_bytes = view.read_bytes()

        # Sync detects conflict and preserves file
        sync_res = engine.sync()
        self.assertEqual(sync_res['status'], 'conflict')
        self.assertEqual(sync_res['conflicts'], [{'source': 'knowledge/v3/outcomes.md', 'reason': 'manual receipt view edit preserved'}])
        self.assertEqual(view.read_bytes(), before_bytes)

        # Second receipt succeeds without ReceiptConflict, reports view_conflicts
        second = engine.receipt('second', 'Synthetic second result', ['notes/canary.md'], 'codex', 'isolated-session')
        self.assertEqual(second['status'], 'succeeded')
        self.assertTrue((self.vault / ('receipts/' + hashlib.sha256(b'second').hexdigest() + '.md')).exists())
        self.assertTrue(any(is_receipt_view_conflict(c) for c in second.get('view_conflicts', [])))

        # Hook delivers healthy canary note to model context despite view conflict
        hook = self._invoke_hook(self.vault, self.state)
        self.assertEqual(hook.returncode, 0)
        self.assertIn('NC-7319', hook.stdout)
        self.assertIn('V3 sync needs attention', hook.stdout)
        self.assertIn('V3 receipt view conflicted', hook.stdout)
        self.assertEqual(view.read_bytes(), before_bytes)

        # Lifecycle events were acknowledged
        pending = list((self.state / 'hook-queue').glob('*.json'))
        self.assertEqual(len(pending), 0)

    def test_restored_state_distinguishes_untracked_receipt_view(self):
        """Restored/copied vault with fresh state diagnoses untracked view without claiming manual edit."""
        engine = SyncEngine(self.vault, self.state)
        engine.sync()
        engine.receipt('seed', 'Synthetic initial result', ['notes/canary.md'], 'codex', 'isolated-session')
        view = self.vault / 'knowledge/v3/outcomes.md'
        before_bytes = view.read_bytes()

        # Simulate restored vault with fresh runtime state and incoming receipt
        fresh_state = self.root / 'fresh-state'
        engine2 = SyncEngine(self.vault, fresh_state)
        incoming = self.vault / ('receipts/' + hashlib.sha256(b'incoming').hexdigest() + '.md')
        incoming.write_text(
            '---\n' + json.dumps({'kind': 'receipt', 'event_id': 'incoming', 'harness': 'codex', 'refs': ['notes/canary.md'], 'visibility': 'internal', 'created_at': '2026-10-12T12:00:00+00:00'}) + '\n---\nSynthetic incoming result\n',
            encoding='utf-8',
        )

        sync_res = engine2.sync()
        self.assertEqual(sync_res['status'], 'conflict')
        # All conflicts must be diagnosed as untracked view, not manual edit
        for conf in sync_res['conflicts']:
            self.assertEqual(conf['reason'], 'untracked receipt view preserved')
            self.assertTrue(is_receipt_view_conflict(conf))
        self.assertEqual(view.read_bytes(), before_bytes)

        # Subsequent receipt succeeds
        second = engine2.receipt('second', 'Synthetic second result', ['notes/canary.md'], 'codex', 'isolated-session')
        self.assertEqual(second['status'], 'succeeded')

        # Hook contains canary
        hook = self._invoke_hook(self.vault, fresh_state)
        self.assertEqual(hook.returncode, 0)
        self.assertIn('NC-7319', hook.stdout)
        pending = list((fresh_state / 'hook-queue').glob('*.json'))
        self.assertEqual(len(pending), 0)

    def test_sync_recover_views_archives_and_regenerates_cleanly(self):
        """sync(recover_views=True) archives modified views to .archive/ and cleanly regenerates views."""
        engine = SyncEngine(self.vault, self.state)
        engine.sync()
        engine.receipt('seed', 'First seed outcome', ['notes/canary.md'], 'codex')
        engine.receipt('seed2', 'Second seed outcome', ['notes/canary.md'], 'codex')

        view = self.vault / 'knowledge/v3/outcomes.md'
        view.write_text(view.read_text(encoding='utf-8') + '\nUser hand-crafted note to be archived.\n', encoding='utf-8')

        # Normal sync sees conflict
        sync_before = engine.sync()
        self.assertEqual(sync_before['status'], 'conflict')
        self.assertEqual(sync_before['conflicts'][0]['reason'], 'manual receipt view edit preserved')

        # Recover views
        sync_recovered = engine.sync(recover_views=True)
        self.assertEqual(sync_recovered['status'], 'succeeded')
        self.assertEqual(sync_recovered['conflicts'], [])
        self.assertTrue(sync_recovered.get('recovered_views'))

        # Check archive file
        archive_entry = sync_recovered['recovered_views'][0]
        self.assertEqual(archive_entry['source'], 'knowledge/v3/outcomes.md')
        archived_file = self.vault / archive_entry['archive']
        self.assertTrue(archived_file.exists())
        self.assertIn('User hand-crafted note to be archived.', archived_file.read_text(encoding='utf-8'))

        # Check new view
        clean_view_text = view.read_text(encoding='utf-8')
        self.assertNotIn('User hand-crafted note to be archived.', clean_view_text)
        self.assertIn('First seed outcome', clean_view_text)
        self.assertIn('Second seed outcome', clean_view_text)

        # Subsequent sync is clean
        sync_after = engine.sync()
        self.assertEqual(sync_after['status'], 'succeeded')
        self.assertEqual(sync_after['conflicts'], [])

    def test_cli_recover_views_command(self):
        """CLI recover-views subcommand and sync --recover-views archive and restore."""
        cli = ROOT / 'scripts/beyin_v3.py'
        subprocess.run([sys.executable, str(cli), '--vault', str(self.vault), '--state', str(self.state), 'init'], check=True)
        subprocess.run([sys.executable, str(cli), '--vault', str(self.vault), '--state', str(self.state), 'sync'], check=True)

        receipt_data = {'event_id': 'cli-ev', 'summary': 'CLI seed outcome', 'refs': ['notes/canary.md']}
        r_file = self.root / 'receipt.json'
        r_file.write_text(json.dumps(receipt_data), encoding='utf-8')
        subprocess.run([sys.executable, str(cli), '--vault', str(self.vault), '--state', str(self.state), 'receipt', '--file', str(r_file)], check=True)

        view = self.vault / 'knowledge/v3/outcomes.md'
        view.write_text(view.read_text(encoding='utf-8') + '\nManual CLI modification.\n', encoding='utf-8')

        # CLI recover-views
        res = subprocess.run(
            [sys.executable, str(cli), '--vault', str(self.vault), '--state', str(self.state), 'recover-views'],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(res.stdout)
        self.assertEqual(data['status'], 'succeeded')
        self.assertEqual(data['conflicts'], [])
        self.assertEqual(len(data['recovered_views']), 1)

    def test_cli_recap_and_context_not_blocked_by_receipt_view_conflict(self):
        """CLI recap and context work when only receipt view conflicts exist."""
        cli = ROOT / 'scripts/beyin_v3.py'
        subprocess.run([sys.executable, str(cli), '--vault', str(self.vault), '--state', str(self.state), 'init'], check=True)
        subprocess.run([sys.executable, str(cli), '--vault', str(self.vault), '--state', str(self.state), 'sync'], check=True)

        receipt_data = {'event_id': 'cli-ev2', 'summary': 'CLI outcome for recap', 'refs': ['notes/canary.md']}
        r_file = self.root / 'receipt2.json'
        r_file.write_text(json.dumps(receipt_data), encoding='utf-8')
        subprocess.run([sys.executable, str(cli), '--vault', str(self.vault), '--state', str(self.state), 'receipt', '--file', str(r_file)], check=True)

        view = self.vault / 'knowledge/v3/outcomes.md'
        view.write_text(view.read_text(encoding='utf-8') + '\nTampered view.\n', encoding='utf-8')

        # recap succeeds
        recap_res = subprocess.run(
            [sys.executable, str(cli), '--vault', str(self.vault), '--state', str(self.state), 'recap', '--limit', '5'],
            capture_output=True,
            text=True,
            check=True,
        )
        recap_data = json.loads(recap_res.stdout)
        self.assertTrue(any('CLI outcome for recap' in item['summary'] for item in recap_data.get('items', [])))

        # context succeeds
        ctx_res = subprocess.run(
            [sys.executable, str(cli), '--vault', str(self.vault), '--state', str(self.state), 'context', 'Nebula memory canary'],
            capture_output=True,
            text=True,
            check=True,
        )
        ctx_data = json.loads(ctx_res.stdout)
        self.assertTrue(any('NC-7319' in r.get('text', '') for r in ctx_data.get('records', [])))

    def test_true_source_conflicts_still_block_queue_drain(self):
        """Adversarial check: genuine source note conflicts (duplicate ID) still block queue drain."""
        (self.vault / 'notes/duplicate_a.md').write_text(
            '---\nid: collision-id\nkind: fact\nvisibility: internal\n---\n# Note A\n',
            encoding='utf-8',
        )
        (self.vault / 'notes/duplicate_b.md').write_text(
            '---\nid: collision-id\nkind: fact\nvisibility: internal\n---\n# Note B\n',
            encoding='utf-8',
        )
        engine = SyncEngine(self.vault, self.state)
        sync_res = engine.sync()
        self.assertEqual(sync_res['status'], 'conflict')
        self.assertTrue(any('duplicate source id' in c.get('reason', '') for c in sync_res['conflicts']))

        from beyin_v3_hook import enqueue_event, drain_queue
        enqueue_event(self.vault, self.state, {'event': 'test'}, 'codex')
        self.assertEqual(len(list((self.state / 'hook-queue').glob('*.json'))), 1)

        result = drain_queue(self.vault, self.state)
        # Because of genuine source conflict, drain must fail and keep queue intact
        self.assertEqual(result['failed'], 1)
        self.assertEqual(len(list((self.state / 'hook-queue').glob('*.json'))), 1)


if __name__ == '__main__':
    unittest.main()
