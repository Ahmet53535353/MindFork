#!/usr/bin/env python3
"""Offline lifecycle, queue and installer tests using isolated synthetic homes."""
import importlib.util
import base64
import re
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'template/.claude/scripts'
HOOK = SCRIPTS / 'beyin_v3_hook.py'
INSTALLER = ROOT / 'scripts/install_v3.py'


def decoded_command(command):
    match = re.search(r'-EncodedCommand\s+([A-Za-z0-9+/=]+)', command, re.IGNORECASE)
    return base64.b64decode(match.group(1)).decode('utf-16le') if match else command


def load_hook():
    if not HOOK.is_file():
        raise AssertionError('Lifecycle adapter not implemented')
    spec = importlib.util.spec_from_file_location('v3_hook_test_subject', HOOK)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class HookInstallerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-hook-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'Synthetic Beyin Ölçüm Space'
        self.vault.mkdir()
        self.state = self.root / 'state outside vault'
        home = self.root / 'isolated-home'
        home.mkdir()
        self.env = {'HOME': str(home), 'USERPROFILE': str(home), 'APPDATA': str(home / 'appdata'),
                    'LOCALAPPDATA': str(home / 'localappdata'), 'TEMP': str(self.root), 'TMP': str(self.root),
                    'PATH': os.defpath, 'PYTHONIOENCODING': 'utf-8', 'PYTHONDONTWRITEBYTECODE': '1',
                    'BEYIN_V3_NO_SPAWN': '1'}
        for key in ('SYSTEMROOT', 'WINDIR'):
            if key in os.environ:
                self.env[key] = os.environ[key]
        sys.path.insert(0, str(SCRIPTS))
        self.addCleanup(lambda: sys.path.remove(str(SCRIPTS)))
        self.hook = load_hook()
        self.payload = {'hook_event_name': 'SessionEnd', 'session_id': 'synthetic-session',
                        'event_id': 'synthetic-event', 'cwd': str(self.vault),
                        'prompt': 'SYNTHETIC_TRANSCRIPT_CANARY_NEVER_PERSIST'}

    def seed(self):
        from beyin_v3_sync import SyncEngine
        source = self.vault / 'notes/task.md'
        source.parent.mkdir()
        source.write_text('---\n' + json.dumps({'id': 'nebula-task', 'kind': 'task', 'revision': 1,
                           'project': 'nebula', 'status': 'active', 'visibility': 'internal'}) +
                          '\n---\nNebula calibration owner is Synthetic Reviewer.\n', encoding='utf-8')
        engine = SyncEngine(self.vault, self.state)
        engine.sync()
        return engine

    def invoke(self, payload, harness='codex', script=None, extra=None):
        result = subprocess.run([sys.executable, str(script or HOOK), '--vault', str(self.vault),
                                 '--state', str(self.state), '--harness', harness] + (extra or []),
                                input=json.dumps(payload), text=True, encoding='utf-8', capture_output=True,
                                cwd=self.vault, env=self.env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertEqual(len(lines), 1, 'Hook stdout must contain exactly one JSON response')
        return json.loads(lines[0])

    def install(self, uninstall=False):
        self.assertTrue(INSTALLER.is_file(), 'Installer not implemented')
        result = subprocess.run([sys.executable, str(INSTALLER), '--vault', str(self.vault), '--state', str(self.state)] +
                                (['--uninstall'] if uninstall else []), capture_output=True, text=True,
                                encoding='utf-8', cwd=self.vault, env=self.env, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_queue_duplicate_and_metadata_only(self):
        first = self.hook.enqueue_event(self.vault, self.state, self.payload, 'codex')
        second = self.hook.enqueue_event(self.vault, self.state, self.payload, 'codex')
        self.assertEqual(first, second)
        pending = list((self.state / 'hook-queue').glob('*.json'))
        self.assertEqual(len(pending), 1)
        self.assertNotIn('SYNTHETIC_TRANSCRIPT_CANARY_NEVER_PERSIST', pending[0].read_text())

    def test_queue_failure_retry_and_no_duplicate_ack(self):
        self.seed()
        from beyin_v3_sync import SyncEngine
        self.hook.enqueue_event(self.vault, self.state, self.payload, 'codex')
        with patch.object(SyncEngine, 'sync', side_effect=RuntimeError('Synthetic worker crash')):
            failed = self.hook.drain_queue(self.vault, self.state)
        self.assertEqual(failed['processed'], 0)
        self.assertEqual(failed['failed'], 1)
        self.assertEqual(failed['pending'], 1)
        recovered = self.hook.drain_queue(self.vault, self.state)
        self.assertEqual(recovered['processed'], 1)
        self.assertEqual(recovered['pending'], 0)
        self.hook.enqueue_event(self.vault, self.state, self.payload, 'codex')
        repeated = self.hook.drain_queue(self.vault, self.state)
        self.assertEqual(repeated['processed'], 0)
        self.assertEqual(repeated['pending'], 0)

    def test_queue_crash_after_sync_before_ack_retries_without_extra_revision(self):
        engine = self.seed()
        source = self.vault / 'notes/task.md'
        source.write_text(source.read_text(encoding='utf-8').replace('"revision": 1', '"revision": 2').replace('owner is', 'new owner is'), encoding='utf-8')
        self.hook.enqueue_event(self.vault, self.state, self.payload, 'codex')
        real_replace = os.replace
        def fail_ack(src, dst, *args, **kwargs):
            if Path(dst).parent.name == 'hook-done':
                raise OSError('Synthetic crash before queue acknowledgement')
            return real_replace(src, dst, *args, **kwargs)
        with patch.object(self.hook.os, 'replace', side_effect=fail_ack):
            try:
                self.hook.drain_queue(self.vault, self.state)
            except OSError:
                pass
        self.assertEqual(len(list((self.state / 'hook-queue').glob('*.json'))), 1)
        history_before = engine.store.history('nebula-task')
        self.assertEqual(history_before[-1]['revision'], 2)
        result = self.hook.drain_queue(self.vault, self.state)
        self.assertEqual(result['processed'], 1)
        self.assertEqual(result['pending'], 0)
        self.assertEqual(engine.store.history('nebula-task'), history_before)

    def test_concurrent_queue_drains_acknowledge_event_once(self):
        self.seed()
        self.hook.enqueue_event(self.vault, self.state, self.payload, 'codex')
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.hook.drain_queue(self.vault, self.state), range(2)))
        self.assertEqual(sum(r['processed'] for r in results), 1)
        self.assertEqual(list((self.state / 'hook-queue').glob('*.json')), [])

    def test_codex_claude_stdin_contexts_equal(self):
        self.seed()
        payload = dict(self.payload, hook_event_name='SessionStart', prompt='Nebula calibration')
        contexts = []
        for harness in ('codex', 'claude'):
            response = self.invoke(payload, harness)
            contexts.append(response['hookSpecificOutput']['additionalContext'])
            self.assertIn('Synthetic Reviewer', contexts[-1])
            self.assertIn('notes/task.md', contexts[-1])
        self.assertEqual(contexts[0], contexts[1])

    def test_restart_context_includes_receipt_as_historical_evidence(self):
        engine = self.seed()
        summary = 'SYNTHETIC_RECEIPT_CONTEXT Latest agreed verification step.'
        engine.receipt('restart-receipt', summary, ['notes/task.md'], 'codex')
        response = self.invoke(dict(self.payload, hook_event_name='SessionStart', prompt='Nebula calibration'))
        context = response['hookSpecificOutput']['additionalContext']
        self.assertIn(summary, context)
        self.assertTrue(any(marker in context.casefold() for marker in ['historical', 'history', 'geçmiş', 'gecmis']))

    def test_stop_stdin_queues_and_explicit_worker_drains(self):
        self.seed()
        response = self.invoke(dict(self.payload, hook_event_name='Stop'), 'claude')
        self.assertEqual(response, {})
        self.assertEqual(len(list((self.state / 'hook-queue').glob('*.json'))), 1)
        drained = self.invoke({}, 'claude', extra=['--drain-queue'])
        self.assertEqual(drained['processed'], 1)
        self.assertEqual(drained['pending'], 0)

    def test_antigravity_start_only_first_invocation_and_final_idle_stop(self):
        self.seed()
        payload = {'hook_event_name': 'PreInvocation', 'conversationId': 'synthetic-agy',
                   'invocationNum': 0, 'event_id': 'ag-start', 'prompt': 'Nebula calibration'}
        response = self.invoke(payload, 'antigravity')
        self.assertIn('Synthetic Reviewer', response['injectSteps'][0]['ephemeralMessage'])
        self.assertEqual(self.invoke(dict(payload, invocationNum=1), 'antigravity'), {})
        before = len(list((self.state / 'hook-queue').glob('*.json')))
        stop = {'hook_event_name': 'Stop', 'conversationId': 'synthetic-agy', 'fullyIdle': False, 'event_id': 'ag-stop'}
        self.assertEqual(self.invoke(stop, 'antigravity'), {'decision': 'stop'})
        self.assertEqual(len(list((self.state / 'hook-queue').glob('*.json'))), before)
        self.assertEqual(self.invoke(dict(stop, fullyIdle=True), 'antigravity'), {'decision': 'stop'})
        self.assertEqual(len(list((self.state / 'hook-queue').glob('*.json'))), before + 1)

    def test_internal_recursion_guard_skips_queue(self):
        self.env['BEYIN_V3_INTERNAL'] = '1'
        self.assertEqual(self.invoke(self.payload), {})
        self.assertEqual(list((self.state / 'hook-queue').glob('*.json')), [])

    def test_install_repeat_preserves_unrelated_configuration_and_trust(self):
        originals = {}
        for relative, payload in [('.claude/settings.local.json', {'hooks': {'SessionStart': [{'matcher': 'synthetic-other', 'hooks': [{'type': 'command', 'command': 'synthetic-unrelated'}]}]}, 'permissions': {'allow': ['Read']}}),
                                  ('.codex/hooks.json', {'hooks': {}, 'trust': {'synthetic-trust': 'unchanged'}}),
                                  ('.agents/hooks.json', {'synthetic-other-agent': {'PreInvocation': []}})]:
            path = self.vault / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding='utf-8')
            originals[relative] = payload
        (self.vault / 'AGENTS.md').write_text('# Synthetic instructions\nKeep this user content.\n', encoding='utf-8')
        (self.vault / 'CLAUDE.md').write_text('# Claude original\n', encoding='utf-8')
        self.install()
        paths = [self.vault / name for name in originals] + [self.vault / 'AGENTS.md', self.vault / 'CLAUDE.md']
        first = [p.read_bytes() for p in paths]
        self.install()
        self.assertEqual([p.read_bytes() for p in paths], first)
        claude = json.loads(paths[0].read_text())
        self.assertEqual(claude['permissions'], originals['.claude/settings.local.json']['permissions'])
        self.assertIn(originals['.claude/settings.local.json']['hooks']['SessionStart'][0], claude['hooks']['SessionStart'])
        self.assertEqual(json.loads(paths[1].read_text())['trust'], {'synthetic-trust': 'unchanged'})
        self.assertIn('synthetic-other-agent', json.loads(paths[2].read_text()))
        self.assertIn('Keep this user content.', (self.vault / 'AGENTS.md').read_text())
        agent_config = json.loads(paths[2].read_text())
        def commands(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == 'command' and isinstance(item, str):
                        yield decoded_command(item)
                    else:
                        yield from commands(item)
            elif isinstance(value, list):
                for item in value:
                    yield from commands(item)
        self.assertTrue(any('beyin_v3_hook.py' in command for command in commands(agent_config)))

    def test_repeat_install_preserves_literal_backslashes_in_instruction_paths(self):
        self.vault = self.root / r'Vault\hooks'
        self.vault.mkdir(parents=True)
        self.install()
        first = (self.vault / 'AGENTS.md').read_bytes()
        self.install()
        self.assertEqual((self.vault / 'AGENTS.md').read_bytes(), first)

    def test_installed_command_runs_with_spaces_and_unicode(self):
        self.install()
        self.seed()
        config = json.loads((self.vault / '.codex/hooks.json').read_text())
        candidates = [hook for matcher in config['hooks']['SessionStart'] for hook in matcher.get('hooks', [])
                      if 'beyin_v3_hook.py' in (decoded_command(hook.get('command', '')) + ' '.join(hook.get('args', [])))]
        self.assertEqual(len(candidates), 1)
        hook = candidates[0]
        command = [hook['command']] + hook['args'] if hook.get('args') else hook['command']
        result = subprocess.run(command, shell=isinstance(command, str), input=json.dumps(dict(self.payload, hook_event_name='SessionStart', prompt='Nebula calibration')),
                                text=True, encoding='utf-8', capture_output=True, cwd=self.vault, env=self.env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Synthetic Reviewer', json.loads(result.stdout)['hookSpecificOutput']['additionalContext'])
        self.assertNotIn('pwsh', str(command).lower())
        if os.name == 'nt':
            self.assertTrue(str(command).lower().split(' -noprofile ')[0].strip(chr(34)).endswith('\\windowspowershell\\v1.0\\powershell.exe'), 'Absolute native launcher must work with the minimal test PATH')
            self.assertIn('beyin_v3_hook.py', decoded_command(command))
        else:
            self.assertNotIn('powershell', str(command).lower())

    def test_cli_unicode_json_with_non_utf8_redirected_environment(self):
        unicode_state = self.root / 'runtime-ölçüm-🔭'
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/beyin_v3.py'), '--vault', str(self.vault),
                                 '--state', str(unicode_state), 'init'], capture_output=True,
                                cwd=self.vault, env=dict(self.env, PYTHONIOENCODING='cp1252'), timeout=20)
        self.assertEqual(result.returncode, 0, 'CLI must emit lossless JSON even with non-UTF8 redirected environment')
        payload = json.loads(result.stdout.decode('utf-8'))
        self.assertTrue(payload['initialized'])
        self.assertEqual(payload['state'], str(unicode_state.resolve()))

    def test_installer_preserves_unicode_json_under_non_utf8_default(self):
        path = self.vault / '.codex/hooks.json'
        path.parent.mkdir(parents=True)
        expected = 'Synthetic ölçüm 🔭 setting'
        path.write_text(json.dumps({'hooks': {}, 'unrelated': expected}, ensure_ascii=False), encoding='utf-8')
        spec = importlib.util.spec_from_file_location('installer_encoding_test_subject', INSTALLER)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        original_read = Path.read_text
        def legacy_default(file, encoding=None, errors=None, **kwargs):
            return original_read(file, encoding=encoding or 'cp1252', errors=errors, **kwargs)
        with patch.object(Path, 'read_text', legacy_default):
            installer.install(self.vault, self.state)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['unrelated'], expected)

    def test_cli_reads_utf8_json_stdin_under_non_utf8_environment(self):
        self.seed()
        summary = 'Synthetic ölçüm 🔭 receipt'
        payload = {'event_id': 'unicode-stdin', 'summary': summary, 'refs': ['notes/task.md']}
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/beyin_v3.py'), '--vault', str(self.vault),
                                 '--state', str(self.state), 'receipt'], input=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                                capture_output=True, cwd=self.vault, env=dict(self.env, PYTHONIOENCODING='cp1252'), timeout=20)
        self.assertEqual(result.returncode, 0)
        receipt = json.loads(result.stdout.decode('utf-8'))
        self.assertIn(summary, (self.vault / receipt['source']).read_text(encoding='utf-8'))

    def test_uninstall_restores_original_files(self):
        for name in ('AGENTS.md', 'CLAUDE.md'):
            (self.vault / name).write_text('Original synthetic ' + name + '\n', encoding='utf-8')
        originals = {name: (self.vault / name).read_bytes() for name in ('AGENTS.md', 'CLAUDE.md')}
        self.install()
        self.install(uninstall=True)
        for name, raw in originals.items():
            self.assertEqual((self.vault / name).read_bytes(), raw)


if __name__ == '__main__':
    unittest.main()
