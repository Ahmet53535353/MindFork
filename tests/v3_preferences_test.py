"""Offline preference and hook behavior contracts; synthetic vaults only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))
import beyin_v3_preferences as prefs


class PreferencesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'Örnek Vault'; self.vault.mkdir()
        self.state = self.root / 'state'

    def cli(self, *args):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/beyin_v3.py'),
            '--vault', str(self.vault), '--state', str(self.state), *args],
            capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def hook(self, event, harness='codex', extra=()):
        payload = {'hook_event_name': event, 'session_id': 'synthetic', 'event_id': event,
                   'conversationId': 'synthetic', 'invocationNum': 0, 'fullyIdle': True}
        r = subprocess.run([sys.executable, str(ROOT / 'template/.claude/scripts/beyin_v3_hook.py'),
            '--vault', str(self.vault), '--state', str(self.state), '--harness', harness, *extra],
            input=json.dumps(payload), capture_output=True, text=True, encoding='utf-8',
            env=dict(os.environ, BEYIN_V3_NO_SPAWN='1'), timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_default_and_custom_roundtrip(self):
        self.assertEqual(prefs.read(self.vault), prefs.PROFILES['normal'])
        self.cli('preferences', '--profile', 'economical', '--interval-minutes', '30')
        result = self.cli('preferences')
        self.assertEqual(result['preferences']['interval_minutes'], 30)
        self.assertEqual(result['preferences']['context_chars'], 2000)
        self.assertFalse(result['model_calls'])
        self.assertFalse(result['timer_installed'])

    def test_invalid_settings_do_not_replace_user_preferences(self):
        prefs.save(self.vault, {}, 'economical')
        before = (self.vault / '.beyin-preferences.json').read_bytes()
        for changes in ({'interval_minutes': -1}, {'interval_minutes': True}, {'context_chars': 999},
                        {'context_mode': 'unknown'}, {'unknown': 1}, {'auto_sync': 'false'}):
            with self.assertRaises(ValueError):
                prefs.save(self.vault, changes)
        self.assertEqual(before, (self.vault / '.beyin-preferences.json').read_bytes())

    def test_manual_hooks_do_not_enqueue_or_inject_across_clients(self):
        prefs.save(self.vault, {}, 'manual')
        for harness in ('codex', 'claude', 'antigravity'):
            event = 'PreInvocation' if harness == 'antigravity' else 'SessionStart'
            result = self.hook(event, harness)
            self.assertNotIn('hookSpecificOutput', result)
            self.assertNotIn('injectSteps', result)
            self.hook('Stop', harness)
        self.assertEqual(list((self.state / 'hook-queue').glob('*.json')), [])

    def test_economical_injects_only_start_and_caps_entire_context(self):
        prefs.save(self.vault, {}, 'economical')
        self.assertEqual(self.hook('UserPromptSubmit'), {})
        result = self.hook('SessionStart')
        text = result['hookSpecificOutput']['additionalContext']
        self.assertIn('Receipt session=', text)
        self.assertLessEqual(len(text), 2000)

    def test_interval_atomic_and_new_session_or_failure_refreshes(self):
        settings = prefs.PROFILES['economical']
        self.assertTrue(prefs.claim_check(self.state, settings, 'Stop', now=1000))
        self.assertFalse(prefs.claim_check(self.state, settings, 'Stop', now=1899))
        with ThreadPoolExecutor(max_workers=4) as pool:
            claimed = list(pool.map(lambda _: prefs.claim_check(self.state, settings, 'Stop', now=1900), range(4)))
        self.assertEqual(sum(claimed), 1)
        self.assertTrue(prefs.claim_check(self.state, settings, 'SessionStart', now=1901))
        (self.state / 'hook-error.json').write_text('{}')
        self.assertTrue(prefs.claim_check(self.state, settings, 'Stop', now=1902))
        self.assertFalse(prefs.claim_check(self.state, prefs.PROFILES['manual'], 'SessionStart', now=2900))

    def test_manual_explicit_context_still_refreshes_current_source(self):
        prefs.save(self.vault, {}, 'manual')
        (self.vault / 'choice.md').write_text('Synthetic project format CSV.', encoding='utf-8')
        self.cli('sync')
        (self.vault / 'choice.md').write_text('Synthetic project format JSON.', encoding='utf-8')
        result = self.cli('context', 'Synthetic project format')
        self.assertIn('JSON', json.dumps(result))
        self.assertNotIn('CSV', json.dumps(result))

    def test_started_worker_respects_disable_but_explicit_drain_is_available(self):
        self.hook('Stop')
        prefs.save(self.vault, {}, 'manual')
        self.assertTrue(self.hook('Stop', extra=('--worker',))['paused'])
        self.assertEqual(len(list((self.state / 'hook-queue').glob('*.json'))), 1)
        self.assertEqual(self.hook('Stop', extra=('--drain-queue',))['pending'], 0)

    def test_install_preserves_preferences_and_ships_working_command(self):
        prefs.save(self.vault, {}, 'economical')
        before = (self.vault / '.beyin-preferences.json').read_bytes()
        r = subprocess.run([sys.executable, str(ROOT / 'scripts/install_v3.py'), '--vault',
                            str(self.vault), '--state', str(self.state)], capture_output=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(before, (self.vault / '.beyin-preferences.json').read_bytes())
        r = subprocess.run([sys.executable, str(self.vault / 'beyin.py'), 'preferences', '--human'],
                           capture_output=True, text=True, encoding='utf-8', timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn('2000 karakter', r.stdout)
        self.assertIn('preferences', self.cli('doctor'))


if __name__ == '__main__':
    unittest.main()
