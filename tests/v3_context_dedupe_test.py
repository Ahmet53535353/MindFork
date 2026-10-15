#!/usr/bin/env python3
"""Session-scoped context deduplication contracts (#363)."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from v3_package_helpers import isolated_path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'template/.claude/scripts'
HOOK = SCRIPTS / 'beyin_v3_hook.py'
spec = importlib.util.spec_from_file_location('v3_dedupe_evaluator', ROOT / 'scripts/evaluate_v3.py')
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)

NOTE_A = 'Quartz observatory calibration: the GoPlus quota is wasted because every candidate is rescanned.'
NOTE_B = 'PostgreSQL performance indexing: btree indexes are ideal for equality and range queries.'


class ContextDedupeHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-dedupe-hook-')
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.vault = root / 'vault'
        self.vault.mkdir()
        self.state = root / 'state'
        home = root / 'home'
        home.mkdir()
        self.env = {'HOME': str(home), 'USERPROFILE': str(home), 'APPDATA': str(home / 'appdata'),
                    'LOCALAPPDATA': str(home / 'localappdata'), 'TEMP': str(root), 'TMP': str(root),
                    'PATH': isolated_path(), 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1',
                    'BEYIN_V3_NO_SPAWN': '1'}
        for key in ('SYSTEMROOT', 'WINDIR'):
            if key in os.environ:
                self.env[key] = os.environ[key]
        sys.path.insert(0, str(SCRIPTS))
        self.addCleanup(lambda: sys.path.remove(str(SCRIPTS)))
        from beyin_v3_sync import SyncEngine
        self.sync_engine = SyncEngine
        self.note_a_path = self.vault / 'knowledge/goplus-quota.md'
        self.note_a_path.parent.mkdir(parents=True)
        self.note_a_path.write_text(NOTE_A, encoding='utf-8')
        self.note_b_path = self.vault / 'knowledge/postgres-index.md'
        self.note_b_path.write_text(NOTE_B, encoding='utf-8')
        self.sync_engine(self.vault, self.state).sync()

    def cli(self, *args):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/beyin_v3.py'),
                                 '--vault', str(self.vault), '--state', str(self.state), *args],
                                capture_output=True, text=True, encoding='utf-8', env=self.env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def invoke(self, event, session_id='test-session', prompt=None, source=None, extra_env=None):
        payload = {'hook_event_name': event, 'session_id': session_id,
                   'event_id': f'evt-{event}', 'cwd': str(self.vault)}
        if prompt is not None:
            payload['prompt'] = prompt
        if source is not None:
            payload['source'] = source
        env = dict(self.env, **(extra_env or {}))
        result = subprocess.run([sys.executable, str(HOOK), '--vault', str(self.vault), '--state', str(self.state),
                                 '--harness', 'claude'], input=json.dumps(payload), capture_output=True,
                                text=True, env=env, check=True)
        return json.loads(result.stdout)

    def test_dedupe_off_by_default_preserves_legacy_repeated_delivery(self):
        # Default behavior: dedupe is off, both turns deliver Note A
        res1 = self.invoke('UserPromptSubmit', prompt='why is the GoPlus quota wasted')
        self.assertIn('knowledge/goplus-quota.md', res1.get('hookSpecificOutput', {}).get('additionalContext', ''))
        res2 = self.invoke('UserPromptSubmit', prompt='why is the GoPlus quota wasted')
        self.assertIn('knowledge/goplus-quota.md', res2.get('hookSpecificOutput', {}).get('additionalContext', ''))

    def test_dedupe_on_suppresses_duplicate_injections_in_same_session(self):
        self.cli('preferences', '--context-dedupe', 'on')
        # Turn 1: delivers Note A
        res1 = self.invoke('UserPromptSubmit', prompt='why is the GoPlus quota wasted')
        self.assertIn('knowledge/goplus-quota.md', res1.get('hookSpecificOutput', {}).get('additionalContext', ''))
        # Turn 2: identical match in same session -> suppressed completely!
        res2 = self.invoke('UserPromptSubmit', prompt='why is the GoPlus quota wasted')
        self.assertEqual(res2, {})

    def test_dedupe_mixed_novel_and_duplicate_delivers_only_novel(self):
        self.cli('preferences', '--context-dedupe', 'on')
        # Turn 1: query matches Note A
        res1 = self.invoke('UserPromptSubmit', prompt='why is the GoPlus quota wasted')
        self.assertIn('knowledge/goplus-quota.md', res1.get('hookSpecificOutput', {}).get('additionalContext', ''))
        self.assertNotIn('knowledge/postgres-index.md', res1.get('hookSpecificOutput', {}).get('additionalContext', ''))

        # Turn 2: query matches both Note A and Note B
        res2 = self.invoke('UserPromptSubmit', prompt='GoPlus quota and postgres performance indexing')
        ctx2 = res2.get('hookSpecificOutput', {}).get('additionalContext', '')
        # Note A was already delivered, so only Note B is novel!
        self.assertNotIn('knowledge/goplus-quota.md', ctx2)
        self.assertIn('knowledge/postgres-index.md', ctx2)

    def test_dedupe_reinjects_when_source_sha256_changes(self):
        self.cli('preferences', '--context-dedupe', 'on')
        # Turn 1: delivers Note A
        res1 = self.invoke('UserPromptSubmit', prompt='why is the GoPlus quota wasted')
        self.assertIn('knowledge/goplus-quota.md', res1.get('hookSpecificOutput', {}).get('additionalContext', ''))

        # User edits Note A on disk and syncs
        self.note_a_path.write_text(NOTE_A + '\nUpdated with fresh benchmarks.', encoding='utf-8')
        self.sync_engine(self.vault, self.state).sync()

        # Turn 2: same prompt now delivers Note A because its source_sha256 changed!
        res2 = self.invoke('UserPromptSubmit', prompt='why is the GoPlus quota wasted')
        ctx2 = res2.get('hookSpecificOutput', {}).get('additionalContext', '')
        self.assertIn('knowledge/goplus-quota.md', ctx2)
        self.assertIn('Updated with fresh benchmarks', ctx2)

    def test_dedupe_resets_on_pre_compact(self):
        self.cli('preferences', '--context-dedupe', 'on')
        # Turn 1: delivers Note A
        res1 = self.invoke('UserPromptSubmit', prompt='why is the GoPlus quota wasted')
        self.assertIn('knowledge/goplus-quota.md', res1.get('hookSpecificOutput', {}).get('additionalContext', ''))

        # Turn 2: suppressed
        res2 = self.invoke('UserPromptSubmit', prompt='why is the GoPlus quota wasted')
        self.assertEqual(res2, {})

        # Compaction occurs
        self.invoke('PreCompact')

        # Turn 3: Note A is delivered again into the compacted context!
        res3 = self.invoke('UserPromptSubmit', prompt='why is the GoPlus quota wasted')
        self.assertIn('knowledge/goplus-quota.md', res3.get('hookSpecificOutput', {}).get('additionalContext', ''))

    def test_dedupe_resets_on_session_start_compact(self):
        self.cli('preferences', '--context-dedupe', 'on')
        # Turn 1: delivers Note A
        res1 = self.invoke('UserPromptSubmit', prompt='why is the GoPlus quota wasted')
        self.assertIn('knowledge/goplus-quota.md', res1.get('hookSpecificOutput', {}).get('additionalContext', ''))

        # Claude Code emits SessionStart with source: compact
        self.invoke('SessionStart', source='compact')

        # Turn 2: Note A is delivered again
        res2 = self.invoke('UserPromptSubmit', prompt='why is the GoPlus quota wasted')
        self.assertIn('knowledge/goplus-quota.md', res2.get('hookSpecificOutput', {}).get('additionalContext', ''))

    def test_dedupe_isolated_per_session(self):
        self.cli('preferences', '--context-dedupe', 'on')
        # Session 1: delivers Note A
        res1 = self.invoke('UserPromptSubmit', session_id='session-1', prompt='why is the GoPlus quota wasted')
        self.assertIn('knowledge/goplus-quota.md', res1.get('hookSpecificOutput', {}).get('additionalContext', ''))

        # Session 2: also delivers Note A (isolated per session)
        res2 = self.invoke('UserPromptSubmit', session_id='session-2', prompt='why is the GoPlus quota wasted')
        self.assertIn('knowledge/goplus-quota.md', res2.get('hookSpecificOutput', {}).get('additionalContext', ''))

    def test_dedupe_session_end_cleans_up(self):
        self.cli('preferences', '--context-dedupe', 'on')
        self.invoke('UserPromptSubmit', session_id='ephemeral-sess', prompt='why is the GoPlus quota wasted')
        import beyin_v3_dedupe as dedupe
        file_path = dedupe._session_file(self.state, 'claude', 'ephemeral-sess')
        self.assertTrue(file_path.is_file())

        self.invoke('SessionEnd', session_id='ephemeral-sess')
        self.assertFalse(file_path.exists())

    def test_dedupe_preferences_and_doctor_roundtrip(self):
        # 1. Default preferences: context_dedupe is off
        prefs_default = self.cli('preferences')
        self.assertEqual(prefs_default.get('context_dedupe'), 'off')
        self.assertFalse((self.vault / '.beyin-preferences.json').exists())

        # 2. Enable context_dedupe
        saved = self.cli('preferences', '--context-dedupe', 'on')
        self.assertEqual(saved['status'], 'saved')
        self.assertEqual(saved['context_dedupe'], 'on')
        self.assertTrue((self.state / 'context-dedupe.json').exists())
        self.assertFalse((self.vault / '.beyin-preferences.json').exists(), 'must not modify vault preference schema')

        # 3. Doctor reports context_dedupe enabled
        doc = self.cli('doctor')
        self.assertEqual(doc.get('context_dedupe', {}).get('enabled'), True)

        # 4. Human readable output
        sys.path.insert(0, str(ROOT / 'scripts'))
        import beyin_entry
        human_prefs = beyin_entry.human_result(saved, 'preferences')
        self.assertIn('Oturum ici tekrar onleme: acik', human_prefs)
        human_doc = beyin_entry.human_result(doc, 'doctor')
        self.assertIn('Oturum ici tekrar onleme: acik', human_doc)

        # 5. Disable context_dedupe
        disabled = self.cli('preferences', '--context-dedupe', 'off')
        self.assertEqual(disabled['context_dedupe'], 'off')

    def test_dedupe_fail_open_on_damaged_ledger(self):
        self.cli('preferences', '--context-dedupe', 'on')
        # Corrupt the session delivery ledger file
        import beyin_v3_dedupe as dedupe
        path = dedupe._session_file(self.state, 'claude', 'damaged-session', create=True)
        path.write_text('{invalid-json-content', encoding='utf-8')

        # Hook must fail open and deliver context normally without crashing
        res = self.invoke('UserPromptSubmit', session_id='damaged-session', prompt='why is the GoPlus quota wasted')
        self.assertIn('knowledge/goplus-quota.md', res.get('hookSpecificOutput', {}).get('additionalContext', ''))


if __name__ == '__main__':
    unittest.main()
