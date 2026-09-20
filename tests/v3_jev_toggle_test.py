#!/usr/bin/env python3
"""Default-off locks for the optional advisor: no config, no import, no network, no text."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from v3_package_helpers import ROOT, install, isolated_env, run_python

CLI = ROOT / 'scripts/beyin_v3.py'
ENTRY = ROOT / 'scripts/beyin_entry.py'
SCRIPTS = ROOT / 'template/.claude/scripts'
HOOK = SCRIPTS / 'beyin_v3_hook.py'
sys.path.insert(0, str(SCRIPTS))
import beyin_v3_jev_client as client

# Distinctive markers: a leak into a file or a status payload is unmistakable.
KEY = 'MARKERFAKEKEYNEVERREAL'
QUERY = 'MARKERQUERYTEXT'
STATEMENT = 'MARKERSTATEMENTTEXT'

# A wrapper takes its paths from argv, runs the real entry point with any network refused,
# then reports which modules the run imported. NetworkAttempted derives from BaseException
# so a hook or CLI "except Exception" cannot swallow an attempted call.
PREAMBLE = '''import contextlib, importlib.util, io, json, socket, sys, urllib.request


class NetworkAttempted(BaseException):
    pass


def refuse(*args, **kwargs):
    raise NetworkAttempted('network attempted')


socket.socket.connect = refuse
urllib.request.OpenerDirector.open = refuse


def report(payload):
    payload['modules'] = sorted(name for name in sys.modules if 'jev' in name)
    sys.stdout.write('REPORT:' + json.dumps(payload))
'''

HOOK_WRAPPER = PREAMBLE + '''
scripts, hook, vault, state = sys.argv[1:5]
sys.path.insert(0, scripts)
spec = importlib.util.spec_from_file_location('hook_under_test', hook)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
for event in ('UserPromptSubmit', 'SessionStart'):
    sys.argv = ['hook', '--vault', vault, '--state', state, '--harness', 'claude']
    sys.stdin = io.StringIO(json.dumps({'hook_event_name': event, 'prompt': 'kisa notlar',
                                        'session_id': 'sentetik-oturum'}))
    with contextlib.redirect_stdout(io.StringIO()):
        module.main()
report({})
'''

DOCTOR_WRAPPER = PREAMBLE + '''
cli, vault, state = sys.argv[1:4]
spec = importlib.util.spec_from_file_location('cli_under_test', cli)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
buffer = io.StringIO()
with contextlib.redirect_stdout(buffer):
    code = module.main(['--vault', vault, '--state', state, 'doctor'])
report({'code': code, 'result': json.loads(buffer.getvalue())})
'''


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class JevToggleTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-jev-toggle-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.state = self.root / 'state'
        self.env = isolated_env(self.root / 'home')
        self.calls = []

    def cli(self, *arguments, env=None):
        return run_python(CLI, ['--vault', self.vault, '--state', self.state, *arguments],
                          ROOT, env or self.env)

    def jev(self, *arguments):
        result = self.cli('jev', *arguments)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def wrapper(self, name, body, arguments):
        path = self.root / name
        path.write_text(body, encoding='utf-8')
        result = run_python(path, arguments, ROOT, self.env)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        text = result.stdout.decode('utf-8', errors='replace')
        self.assertIn('REPORT:', text, text)
        return json.loads(text.split('REPORT:', 1)[1])

    def card(self):
        return dict(id='one', title='Sentetik', statement=STATEMENT, scope='user', domains=['demo'])

    def transport(self, endpoint, body, key, timeout):
        self.calls.append(body)
        return dict(answers={name: dict(type='score', score=1.5) for name in body['questions']},
                    usage=dict(input_tokens=7, output_tokens=2))

    def forbidden(self, *arguments):
        raise AssertionError('transport must not be called')


class FreshInstallTest(JevToggleTestCase):
    def test_install_leaves_no_advisor_state_and_no_key_anywhere(self):
        env = dict(self.env, TYPESAFE_API_KEY=KEY, TYPESAFE_BASE_URL='https://marker.invalid')
        installed = install(self.vault, self.state, env)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        for name in ('jev.json', 'jev.disabled', 'jev-calls.jsonl'):
            self.assertFalse((self.state / name).exists(), name)
        for root in (self.vault, self.state):
            for path in root.rglob('*'):
                if path.is_file() and not path.is_symlink():
                    self.assertNotIn(KEY.encode(), path.read_bytes(), str(path))


class NoConfigImportTest(JevToggleTestCase):
    def test_hook_without_config_never_imports_the_client(self):
        report = self.wrapper('hook_wrapper.py', HOOK_WRAPPER, [SCRIPTS, HOOK, self.vault, self.state])
        self.assertEqual(report['modules'], [])
        self.assertFalse((self.state / 'jev.json').exists())

    def test_doctor_without_config_reports_off_without_importing_the_client(self):
        report = self.wrapper('doctor_wrapper.py', DOCTOR_WRAPPER, [CLI, self.vault, self.state])
        self.assertEqual(report['code'], 0)
        self.assertEqual(report['modules'], [])
        self.assertEqual(report['result']['jev'], {'mode': 'off', 'configured': False})
        self.assertIs(report['result']['automatic_model_calls'], False)

    def test_doctor_status_field_ignores_the_advisor(self):
        before = json.loads(self.cli('doctor').stdout)
        self.jev('on', '--enable', 'auto_context')
        after = json.loads(self.cli('doctor').stdout)
        self.assertEqual(after['status'], before['status'])
        self.assertEqual(after['jev']['mode'], 'on')
        self.assertIs(after['automatic_model_calls'], True)


class ModeCommandTest(JevToggleTestCase):
    def test_on_then_status_keeps_auto_context_off(self):
        changed = self.jev('on')
        self.assertTrue(changed['changed'])
        current = self.jev('status')
        self.assertEqual(current['mode'], 'on')
        self.assertEqual(current['saved_mode'], 'on')
        for name in ('context', 'review', 'answer'):
            self.assertIs(current['features'][name], True, name)
        self.assertIs(current['features']['auto_context'], False)
        self.assertIs(current['automatic_model_calls'], False)
        self.assertNotIn('notice', current)
        self.assertIn('TYPESAFE_API_KEY', current['warning'])

    def test_auto_context_is_announced_and_off_keeps_the_feature_list(self):
        enabled = self.jev('on', '--enable', 'auto_context')
        self.assertIs(enabled['features']['auto_context'], True)
        self.assertIs(enabled['automatic_model_calls'], True)
        self.assertIn('private notes are never sent', enabled['notice'].lower())
        disabled = self.jev('off')
        self.assertEqual(disabled['mode'], 'off')
        self.assertIs(disabled['features']['auto_context'], True)
        self.assertIs(disabled['automatic_model_calls'], False)
        self.assertNotIn('warning', disabled)

    def test_shadow_can_disable_one_feature(self):
        result = self.jev('shadow', '--disable', 'answer')
        self.assertEqual(result['mode'], 'shadow')
        self.assertIs(result['features']['answer'], False)
        self.assertIs(result['features']['context'], True)

    def test_status_rejects_feature_flags(self):
        result = self.cli('jev', 'status', '--enable', 'context')
        self.assertEqual(result.returncode, 1)
        self.assertIn('status', json.loads(result.stderr)['message'])

    def test_cli_feature_choices_mirror_the_client(self):
        self.assertEqual(load_module('v3_jev_toggle_cli', CLI).JEV_FEATURES, client.FEATURES)


class ConfigFileTest(JevToggleTestCase):
    def test_write_is_atomic_private_and_keeps_hand_added_keys(self):
        self.state.mkdir(parents=True)
        (self.state / 'jev.json').write_text('{"mode": "off", "timeout": 2}', encoding='utf-8')
        self.jev('on')
        path = self.state / 'jev.json'
        supplied = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(supplied['mode'], 'on')
        self.assertEqual(supplied['timeout'], 2)
        self.assertEqual(sorted(entry.name for entry in self.state.iterdir()), ['jev.json'])
        if os.name != 'nt':
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_broken_config_fails_the_command_and_is_left_untouched(self):
        self.state.mkdir(parents=True)
        path = self.state / 'jev.json'
        path.write_text('{bozuk', encoding='utf-8')
        result = self.cli('jev', 'on')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stderr)['message'], 'config_invalid')
        self.assertEqual(path.read_text(encoding='utf-8'), '{bozuk')


class KillSwitchTest(JevToggleTestCase):
    def test_env_and_file_stop_calls_without_changing_the_saved_mode(self):
        client.set_mode(self.state, 'on')
        switches = [('env', {'BEYIN_JEV_DISABLE': '1'}), ('file', {})]
        for name, environment in switches:
            with self.subTest(switch=name):
                if name == 'file':
                    (self.state / 'jev.disabled').write_text('', encoding='utf-8')
                with patch.dict(os.environ, environment, clear=True):
                    current = client.status(self.state)
                    advice = client.evaluate(self.state, QUERY, [self.card()], transport=self.forbidden)
                self.assertEqual(current['mode'], 'off')
                self.assertEqual(current['saved_mode'], 'on')
                self.assertIs(current['kill_switch'], True)
                self.assertEqual(advice['mode'], 'off')
        self.assertFalse(self.calls)

    def test_disabled_feature_returns_off_before_any_call(self):
        client.set_mode(self.state, 'on', disable=['answer'])
        item = dict(id='a', claim='Sentetik iddia.', quotes=[STATEMENT], context=[])
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': KEY}, clear=True):
            advice = client.evaluate(self.state, '', [item], purpose='answer_check', transport=self.forbidden)
        self.assertEqual(advice['mode'], 'off')
        self.assertIn('feature_disabled', advice['diagnostics'])
        self.assertFalse(self.calls)


class CallLogTest(JevToggleTestCase):
    def test_one_call_writes_one_counter_row_without_text_or_key(self):
        client.set_mode(self.state, 'on')
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': KEY}, clear=True):
            advice = client.evaluate(self.state, QUERY, [self.card()], transport=self.transport)
        self.assertFalse(advice['degraded'], advice['diagnostics'])
        self.assertEqual(len(self.calls), 1)
        raw = (self.state / 'jev-calls.jsonl').read_text(encoding='utf-8')
        rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['purpose'], 'retrieval')
        self.assertEqual(rows[0]['input_tokens'], 7)
        for marker in (QUERY, STATEMENT, KEY):
            self.assertNotIn(marker, raw)

    def test_oversized_log_shrinks_and_stays_valid_jsonl(self):
        self.state.mkdir(parents=True)
        path = self.state / 'jev-calls.jsonl'
        row = json.dumps(dict(purpose='retrieval', mode='on', at=round(time.time(), 3))) + '\n'
        path.write_text(row * (client.LOG_LIMIT // len(row) + 50), encoding='utf-8', newline='')
        before = path.stat().st_size
        self.assertGreater(before, client.LOG_LIMIT)
        client.log_event(self.state, dict(purpose='retrieval', mode='on'))
        self.assertLess(path.stat().st_size, before)
        lines = [line for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        self.assertTrue(lines)
        for line in lines:
            self.assertIsInstance(json.loads(line), dict)


class StatusReportTest(JevToggleTestCase):
    def test_key_presence_is_reported_but_never_the_value(self):
        client.set_mode(self.state, 'shadow')
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': KEY}, clear=True):
            present = client.status(self.state)
        with patch.dict(os.environ, {}, clear=True):
            absent = client.status(self.state)
        self.assertIs(present['key_present'], True)
        self.assertIs(absent['key_present'], False)
        self.assertNotIn(KEY, json.dumps(present))

    def test_human_output_is_ascii_for_jev_and_doctor(self):
        entry = load_module('v3_jev_toggle_entry', ENTRY)
        client.set_mode(self.state, 'on', enable=['auto_context'])
        with patch.dict(os.environ, {}, clear=True):
            current = dict(client.status(self.state), notice='auto_context', warning='key')
        rendered = [entry.human_result(current, 'jev'),
                    entry.human_result({'status': 'never_seen', 'jev': current}, 'doctor'),
                    entry.human_result({'status': 'never_seen', 'jev': {'mode': 'off', 'configured': False}}, 'doctor')]
        for text in rendered:
            self.assertEqual(text, text.encode('ascii', 'replace').decode('ascii'))
        self.assertIn('Jev: acik', rendered[0])
        self.assertIn('otomatik baglam: acik', rendered[1])
        self.assertIn('Jev: kapali', rendered[2])


if __name__ == '__main__':
    unittest.main()
