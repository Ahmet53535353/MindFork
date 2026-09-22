import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
import sys
SCRIPTS = ROOT / 'template/.claude/scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import importlib.util
_spec = importlib.util.spec_from_file_location('beyin_entry', ROOT / 'scripts/beyin_entry.py')
beyin_entry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(beyin_entry)

import beyin_v3_hook as hook
import beyin_v3_hermes as hermes
from beyin_v3_sync import SyncEngine
from beyin_v3_projections import refresh_gaps, record_checkpoints


class TestIssue78ReceiptCoverageAndUnattended(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='beyin_test_issue78_'))
        self.vault = self.tmp / 'vault'
        self.state = self.tmp / 'state'
        self.vault.mkdir(parents=True)
        self.state.mkdir(parents=True)
        (self.vault / '🔮 850-Companion').mkdir(parents=True)
        (self.vault / '🔮 850-Companion/Core.md').write_text('# Core\nTest vault\n', encoding='utf-8')
        (self.vault / 'daily').mkdir(parents=True)
        (self.vault / 'receipts').mkdir(parents=True)
        (self.vault / 'knowledge').mkdir(parents=True)
        (self.vault / '.claude/preferences.json').parent.mkdir(parents=True)
        (self.vault / '.claude/preferences.json').write_text(json.dumps({
            'auto_sync': True, 'context_mode': 'session', 'context_chars': 4000,
            'secret_filter': True, 'update_notifications': True
        }), encoding='utf-8')
        (self.vault / '.beyin-runtime.json').write_text(json.dumps({'state': str(self.state)}), encoding='utf-8')
        (self.state / 'v3-install.json').write_text(json.dumps({'version': '3.2.1'}), encoding='utf-8')
        SyncEngine(self.vault, self.state).sync()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _enqueue(self, event, session_id, harness='claude', unattended=False, extra_env=None):
        payload = {
            'hook_event_name': event,
            'session_id': session_id,
            'event_id': f"{event}_{session_id}_{time.time()}",
            'prompt': 'hello',
        }
        if unattended:
            payload['unattended'] = True

        old_env = dict(os.environ)
        if extra_env:
            os.environ.update(extra_env)
        try:
            return hook.enqueue_event(self.vault, self.state, payload, harness)
        finally:
            os.environ.clear()
            os.environ.update(old_env)

    def test_unattended_sessions_not_counted_as_missing_receipt_gaps(self):
        """Issue 78: Subagents and unattended runs (BEYIN_INVOKED_BY) must not create false gaps."""
        # 1. Simulate an unattended session via BEYIN_INVOKED_BY env
        self._enqueue('SessionStart', 'subagent_sess_1', extra_env={'BEYIN_INVOKED_BY': 'claude-subagent'})
        self._enqueue('UserPromptSubmit', 'subagent_sess_1', extra_env={'BEYIN_INVOKED_BY': 'claude-subagent'})
        self._enqueue('Stop', 'subagent_sess_1', extra_env={'BEYIN_INVOKED_BY': 'claude-subagent'})

        # 2. Simulate an unattended session via payload['unattended'] = True
        self._enqueue('SessionStart', 'subagent_sess_2', unattended=True)
        self._enqueue('Stop', 'subagent_sess_2', unattended=True)

        # 3. Simulate an unattended session via BEYIN_UNATTENDED=1
        self._enqueue('SessionStart', 'subagent_sess_3', extra_env={'BEYIN_UNATTENDED': '1'})
        self._enqueue('Stop', 'subagent_sess_3', extra_env={'BEYIN_UNATTENDED': '1'})

        # Drain the queue
        result = hook.drain_queue(self.vault, self.state)
        self.assertGreater(result['processed'], 0)

        gaps_file = self.state / 'receipt-gaps.json'
        self.assertTrue(gaps_file.exists())
        gaps_data = json.loads(gaps_file.read_text(encoding='utf-8'))

        self.assertEqual(gaps_data.get('potential_missing_receipts'), 0,
                         "Unattended sessions should not be counted as potential missing receipts!")
        self.assertEqual(len(gaps_data.get('checkpoints', [])), 0,
                         "Unattended sessions should not be in the missing checkpoints list!")
        self.assertEqual(gaps_data.get('unattended_checkpoints'), 3,
                         "Should track unattended checkpoints count separately")

    def test_receipt_coverage_ratio_calculation(self):
        """Issue 78: Coverage ratio must report covered vs total interactive sessions, excluding unattended."""
        engine = SyncEngine(self.vault, self.state)

        # Session 1: Interactive session with a receipt
        sess1 = 'interactive_1'
        self._enqueue('SessionStart', sess1)
        self._enqueue('UserPromptSubmit', sess1)
        self._enqueue('Stop', sess1)

        # Drain and add receipt for Session 1
        hook.drain_queue(self.vault, self.state)
        gaps = json.loads((self.state / 'receipt-gaps.json').read_text(encoding='utf-8'))['checkpoints']
        self.assertEqual(len(gaps), 1)
        sess1_hashed = gaps[0]['session']

        engine.note_create('notes/demo.md', 'Work completed.', {'id': 'demo'})
        engine.receipt('evt_sess1', 'Completed work', ['notes/demo.md'], 'claude', session=sess1_hashed)
        engine.sync()

        # Session 2: Interactive session WITHOUT a receipt
        sess2 = 'interactive_2'
        self._enqueue('SessionStart', sess2)
        self._enqueue('UserPromptSubmit', sess2)
        self._enqueue('Stop', sess2)

        # Session 3: Unattended session (must NOT pollute the interactive ratio)
        sess3 = 'unattended_3'
        self._enqueue('SessionStart', sess3, extra_env={'BEYIN_INVOKED_BY': 'runner'})
        self._enqueue('UserPromptSubmit', sess3, extra_env={'BEYIN_INVOKED_BY': 'runner'})
        self._enqueue('Stop', sess3, extra_env={'BEYIN_INVOKED_BY': 'runner'})

        hook.drain_queue(self.vault, self.state)

        gaps_file = self.state / 'receipt-gaps.json'
        gaps_data = json.loads(gaps_file.read_text(encoding='utf-8'))

        # Only session 2 should be missing
        self.assertEqual(gaps_data.get('potential_missing_receipts'), 1)
        self.assertEqual(gaps_data.get('unattended_checkpoints'), 1)

        coverage = gaps_data.get('receipt_coverage')
        self.assertIsNotNone(coverage, "receipt_coverage must be present in receipt-gaps.json")
        self.assertEqual(coverage.get('total'), 2, "Interactive total should be 2 (sess1 + sess2)")
        self.assertEqual(coverage.get('covered'), 1, "Covered should be 1 (sess1)")
        self.assertEqual(coverage.get('missing'), 1, "Missing should be 1 (sess2)")
        self.assertEqual(coverage.get('ratio'), 0.5, "Coverage ratio should be 1/2 = 0.5")

        # Time windows
        self.assertIn('last_7d', coverage)
        self.assertIn('last_30d', coverage)
        self.assertEqual(coverage['last_7d']['total'], 2)
        self.assertEqual(coverage['last_7d']['covered'], 1)
        self.assertEqual(coverage['last_7d']['ratio'], 0.5)

        # Verify CLI doctor command output
        cmd = [sys.executable, str(ROOT / 'scripts/beyin_v3.py'), '--vault', str(self.vault),
               '--state', str(self.state), 'doctor']
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        doc_result = json.loads(proc.stdout)
        self.assertEqual(doc_result.get('potential_missing_receipts'), 1)
        self.assertEqual(doc_result.get('unattended_checkpoints'), 1)
        self.assertIsNotNone(doc_result.get('receipt_coverage'))
        self.assertEqual(doc_result['receipt_coverage']['ratio'], 0.5)

        # Verify human doctor rendering
        human_text = beyin_entry.human_result(doc_result, 'doctor')
        self.assertIn('Makbuz kapsami: %50 (1/2 oturum', human_text)
        self.assertIn('Gozetimsiz oturum: 1 (makbuz hesabindan muaf)', human_text)

    def test_unattended_session_still_receives_memory_context(self):
        """Even unattended/subagent sessions should still receive injected memory context."""
        payload = json.dumps({'hook_event_name': 'SessionStart', 'session_id': 'subagent_ctx_1'})
        env = dict(os.environ, BEYIN_INVOKED_BY='claude-subagent', BEYIN_V3_NO_SPAWN='1')
        cmd = [sys.executable, str(ROOT / 'template/.claude/scripts/beyin_v3_hook.py'),
               '--vault', str(self.vault), '--state', str(self.state), '--harness', 'claude']
        proc = subprocess.run(cmd, input=payload, capture_output=True, text=True, env=env, check=True)
        res = json.loads(proc.stdout)
        self.assertIn('hookSpecificOutput', res)
        self.assertIn('Test vault', res['hookSpecificOutput']['additionalContext'])

    def test_legacy_receipt_checkpoints_schema_migration(self):
        """Ensure older receipt_checkpoints SQLite table without unattended column migrates cleanly."""
        engine = SyncEngine(self.vault, self.state)
        with engine.store._connect() as db:
            db.execute('DROP TABLE IF EXISTS receipt_checkpoints')
            # Legacy table missing 'unattended'
            db.execute('CREATE TABLE receipt_checkpoints(harness TEXT, session TEXT, at REAL, turn_at REAL DEFAULT 0, PRIMARY KEY(harness,session))')
            db.execute("INSERT INTO receipt_checkpoints VALUES ('claude', 'old_session', 1000.0, 500.0)")

        # Trigger refresh_gaps through sync
        engine.sync()

        # Schema should now have unattended column
        with engine.store._connect() as db:
            cols = {row[1] for row in db.execute('PRAGMA table_info(receipt_checkpoints)')}
            self.assertIn('unattended', cols)

        gaps = json.loads((self.state / 'receipt-gaps.json').read_text(encoding='utf-8'))
        self.assertEqual(gaps['potential_missing_receipts'], 1)
        self.assertEqual(gaps['checkpoints'][0]['session'], 'old_session')

    def test_hermes_unattended_platforms_sets_unattended_flag(self):
        """Hermes plugin should set payload['unattended'] = True for UNATTENDED_PLATFORMS."""
        calls = []

        def fake_run_hook(vault, state, payload, python=None):
            calls.append(payload)
            return 'fake context'

        orig_run_hook = hermes.run_hook
        hermes.run_hook = fake_run_hook
        try:
            hooks = hermes.make_hooks(self.vault, self.state)
            # Platform 'cron' is unattended
            hooks['pre_llm_call'](session_id='hermes_cron_1', is_first_turn=True, platform='cron')
            self.assertTrue(calls[-1].get('unattended'))

            # Platform 'cli' is interactive
            hooks['pre_llm_call'](session_id='hermes_cli_1', is_first_turn=True, platform='cli')
            self.assertNotIn('unattended', calls[-1])

            # Finalize cron session (skips run_hook entirely)
            hooks['on_session_finalize'](session_id='hermes_cron_1')
            self.assertEqual(len(calls), 2)
        finally:
            hermes.run_hook = orig_run_hook


if __name__ == '__main__':
    unittest.main()
