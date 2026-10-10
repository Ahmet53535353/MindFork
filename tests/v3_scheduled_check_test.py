#!/usr/bin/env python3
"""scheduled-check (#267): sync then doctor for an OS scheduler; opt-in OS notification on a change."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v3_package_helpers import inherited_env

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'template/.claude/scripts'
PRIVATE = 'Maas-Butce'  # a note name that must never reach a notification


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scheduled = load('beyin_v3_scheduled_under_test', SCRIPTS / 'beyin_v3_scheduled.py')

# Stands in for the CLI in run(): prints the sync or doctor JSON the test wrote beside it.
FAKE_CLI = '''import json, pathlib, sys
outputs = json.loads((pathlib.Path(__file__).parent / 'outputs.json').read_text(encoding='utf-8'))
print(json.dumps(outputs[sys.argv[-1]]))
'''
HEALTHY = {'sync': {'status': 'succeeded', 'conflicts': [], 'warnings': []}, 'doctor': {'status': 'observed_metadata'}}
TROUBLED = {'sync': {'status': 'conflict', 'warnings': [],
                     'conflicts': [{'id': 'a', 'reason': PRIVATE}, {'source': 'notes/' + PRIVATE + '.md'}]},
            'doctor': {'status': 'needs_attention', 'skill_conflicts': [PRIVATE], 'hook_paths': {'status': 'stale'}}}


class CliTest(unittest.TestCase):
    """The real CLI against a synthetic vault: exit codes, the record, the lock, doctor."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='v3-scheduled-')
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.vault, self.state = root / 'vault', root / 'state'
        (self.vault / 'notes').mkdir(parents=True)
        (self.vault / 'notes/a.md').write_text('---\n{"id": "a"}\n---\nSynthetic note.\n', encoding='utf-8')
        self.env = inherited_env(BEYIN_V3_NO_SPAWN='1')

    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/beyin_v3.py'), '--vault', str(self.vault),
                               '--state', str(self.state), *args], capture_output=True, text=True,
                              encoding='utf-8', env=self.env, timeout=300)

    def snapshot(self):
        return {path: path.read_bytes() for path in self.vault.rglob('*') if path.is_file()}

    def test_healthy_run_is_recorded_and_shown_by_doctor_without_touching_notes(self):
        self.assertEqual(json.loads(self.cli('doctor').stdout)['scheduled_check'], {'status': 'never_run'})
        before = self.snapshot()
        ran = self.cli('scheduled-check')
        self.assertEqual(ran.returncode, 0, ran.stderr)
        record = json.loads(ran.stdout)
        self.assertEqual((record['status'], record['sync_status'], record['issues']), ('ok', 'succeeded', {}))
        self.assertEqual(before, self.snapshot())
        self.assertNotIn('notification', record, 'no notification without --notify')
        shown = json.loads(self.cli('doctor').stdout)['scheduled_check']
        self.assertEqual((shown['status'], shown['finished_at'], shown['age_hours']), ('ok', record['finished_at'], 0))

    def test_needs_attention_exits_four_and_a_usage_error_keeps_two(self):
        (self.vault / 'notes/b.md').write_text('---\n{"id": "a"}\n---\nSame id, other text.\n', encoding='utf-8')
        ran = self.cli('scheduled-check')
        self.assertEqual(ran.returncode, 4, ran.stdout + ran.stderr)
        record = json.loads(ran.stdout)
        self.assertEqual((record['status'], record['issues']), ('needs_attention', {'sync_conflict': 1}))
        typo = self.cli('scheduled-check', '--notfy')
        self.assertEqual(typo.returncode, 2, 'argparse owns 2; it must never mean "needs attention"')
        self.assertEqual(json.loads((self.state / 'scheduled-check.json').read_text(encoding='utf-8'))['finished_at'],
                         record['finished_at'], 'a usage error records nothing')

    def test_a_running_check_skips_and_a_dead_runs_lock_file_does_not(self):
        self.state.mkdir(parents=True)
        lock = self.state / 'scheduled-check.lock'
        lock.write_text('12345', encoding='ascii')  # left by a run that died: no OS lock behind it
        old = time.time() - 30
        os.utime(lock, (old, old))
        first = self.cli('scheduled-check')
        self.assertEqual(first.returncode, 0, first.stderr)
        holder = subprocess.Popen(
            [sys.executable, '-c', 'import importlib.util, sys\n'
             'spec = importlib.util.spec_from_file_location("s", sys.argv[1]); m = importlib.util.module_from_spec(spec)\n'
             'spec.loader.exec_module(m)\nh = open(sys.argv[2], "a+b")\nprint(m._lock(h), flush=True)\nsys.stdin.read()\n',
             str(SCRIPTS / 'beyin_v3_scheduled.py'), str(lock)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.addCleanup(holder.stdout.close)
        self.addCleanup(holder.wait, 30)
        self.addCleanup(holder.stdin.close)
        self.assertEqual(holder.stdout.readline().strip(), 'True')
        held = self.cli('scheduled-check')
        self.assertEqual(held.returncode, 3, held.stderr)
        self.assertEqual(json.loads(held.stdout), {'status': 'already_running'})
        self.assertTrue(lock.exists(), 'another run\'s lock is never deleted')
        holder.stdin.close()
        holder.wait(30)
        after = self.cli('scheduled-check')
        self.assertEqual(after.returncode, 0, 'the OS released the lock with its holder: ' + after.stderr)

    def test_runs_started_together_over_an_old_lock_file_never_crash(self):
        self.state.mkdir(parents=True)
        lock = self.state / 'scheduled-check.lock'
        lock.write_text('12345', encoding='ascii')
        old = time.time() - 3 * 3600
        os.utime(lock, (old, old))
        command = [sys.executable, str(ROOT / 'scripts/beyin_v3.py'), '--vault', str(self.vault), '--state',
                   str(self.state), 'scheduled-check']
        runs = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                 encoding='utf-8', env=self.env) for _ in range(6)]
        results = [(run.wait(300), run.communicate()) for run in runs]
        codes = sorted(code for code, _ in results)
        self.assertTrue(set(codes) <= {0, 3}, results)
        self.assertIn(0, codes)

    def test_doctor_passes_only_known_fields(self):
        self.state.mkdir(parents=True)
        (self.state / 'scheduled-check.json').write_text(json.dumps({
            'schema': 1, 'status': 'error', 'finished_at': '2026-01-01T00:00:00Z', 'error': 'notes/' + PRIVATE + '.md',
            'issues': {'sync_conflict': 2, 'injected': 9, 'task': 'many'}, 'note': PRIVATE,
            'notification': '<b>x</b>', 'last_notified_at': 'yesterday'}), encoding='utf-8')
        shown = json.loads(self.cli('doctor').stdout)['scheduled_check']
        self.assertEqual(set(shown), {'status', 'finished_at', 'age_hours', 'notify', 'issues', 'error'})
        self.assertEqual((shown['issues'], shown['error'], shown['notify']), ({'sync_conflict': 2}, 'other', False))
        self.assertNotIn(PRIVATE, json.dumps(shown))
        (self.state / 'scheduled-check.json').write_text('{"status": "ok", "finished_at": 7}', encoding='utf-8')
        self.assertEqual(json.loads(self.cli('doctor').stdout)['scheduled_check'], {'status': 'unreadable'})

    def test_return_result_mode_hands_back_the_record_and_the_code(self):
        # The installed entry point calls main(return_result=True) in human mode.
        (self.vault / 'notes/b.md').write_text('---\n{"id": "a"}\n---\nSame id, other text.\n', encoding='utf-8')
        cli = load('beyin_v3_cli_under_test', ROOT / 'scripts/beyin_v3.py')
        with mock.patch.dict(os.environ, {'BEYIN_V3_NO_SPAWN': '1'}):
            result, code = cli.main(['--vault', str(self.vault), '--state', str(self.state), 'scheduled-check'],
                                    return_result=True)
        self.assertEqual((result['status'], code), ('needs_attention', 4))
        entry = load('beyin_entry_under_test', ROOT / 'scripts/beyin_entry.py')
        text = entry.human_result(result, 'scheduled-check')
        self.assertNotIn('tamamlanamadi', text)
        self.assertIn('beyin.py doctor', text)
        self.assertIn('tamamlanamadi', entry.human_result({'status': 'error', 'error': 'RuntimeError'}, 'scheduled-check'))


class NotifyTest(unittest.TestCase):
    """run() with a stand-in CLI and the notifier replaced: when it speaks, what it says."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='v3-scheduled-notify-')
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.vault, self.state, self.cli = root / 'vault', root / 'state', root / 'fake/cli.py'
        self.vault.mkdir()
        self.cli.parent.mkdir()
        self.cli.write_text(FAKE_CLI, encoding='utf-8')
        self.shown = []
        self.answer = 'shown'
        self.now = 1_800_000_000

    def display(self, text):
        self.shown.append(text)
        return self.answer

    def step(self, outputs, notify=True, days=1):
        (self.cli.parent / 'outputs.json').write_text(json.dumps(outputs), encoding='utf-8')
        self.now += days * 86400
        record, code = scheduled.run(self.vault, self.state, self.cli, notify=notify, now=self.now,
                                     display=self.display)
        return record, code

    def test_only_a_change_or_a_weekly_reminder_speaks(self):
        self.assertEqual(self.step(HEALTHY)[1], 0)
        self.assertEqual(self.shown, [], 'a first healthy run stays quiet')
        record, code = self.step(TROUBLED)
        self.assertEqual((code, record['notification'], len(self.shown)), (4, 'shown', 1))
        self.assertEqual(self.shown[0], 'Beyin: sync cakismasi (2), hook uyarisi (1), skill/talimat cakismasi (1)'
                                        ' - ayrinti: beyin.py doctor')
        for _ in range(6):
            self.step(TROUBLED)
        self.assertEqual(len(self.shown), 1, 'the same problem is not repeated every night')
        self.step(TROUBLED)  # seven days after the first notification
        self.assertEqual(len(self.shown), 2)
        self.assertTrue(self.shown[1].startswith('Beyin (hatirlatma): sync cakismasi (2)'))
        self.step(HEALTHY)
        self.assertEqual(self.shown[2], 'Beyin: sorunlar giderildi, kasa saglikli.')
        self.step(HEALTHY)
        self.assertEqual(len(self.shown), 3)
        self.assertFalse(any(PRIVATE in text or '.md' in text for text in self.shown))

    def test_without_notify_nothing_is_shown(self):
        record, code = self.step(TROUBLED, notify=False)
        self.assertEqual((code, self.shown, record['notify']), (4, [], False))
        self.assertFalse((self.state / 'scheduled-notice.json').exists())

    def test_a_failed_check_is_an_error_not_a_change(self):
        self.step(TROUBLED)
        (self.cli.parent / 'outputs.json').write_text('{}', encoding='utf-8')
        self.now += 86400
        record, code = scheduled.run(self.vault, self.state, self.cli, notify=True, now=self.now, display=self.display)
        self.assertEqual((record['status'], record['error'], code), ('error', 'RuntimeError', 1))
        self.assertEqual(len(self.shown), 1)
        self.step(TROUBLED)
        self.assertEqual(len(self.shown), 1, 'still the same problem once the check runs again')

    def test_an_unshown_notification_is_said_once_at_the_next_session(self):
        self.answer = 'unavailable'
        record, _ = self.step(TROUBLED)
        self.assertEqual(record['notification'], 'unavailable')
        line = scheduled.session_notice(self.state)
        self.assertTrue(line.startswith('Zamanlanmis denetim bildirimi gosterilemedi; kullaniciya soyle: Beyin: sync'))
        self.assertTrue(line.endswith('\n') and line.count('\n') == 1)
        self.assertEqual(scheduled.session_notice(self.state), '', 'said once')
        self.answer = 'failed'
        self.step(HEALTHY)
        self.assertIn('sorunlar giderildi', scheduled.session_notice(self.state))
        (self.state / 'scheduled-notice.json').write_text(json.dumps({'text': 'Beyin: ' + PRIVATE + '\nrm -rf'}),
                                                           encoding='utf-8')
        self.assertEqual(scheduled.session_notice(self.state), '', 'a hand-written multi-line text is not passed on')

    def test_a_shown_notification_clears_an_older_pending_one(self):
        self.answer = 'failed'
        self.step(TROUBLED)
        self.assertTrue((self.state / 'scheduled-notice.json').exists())
        self.answer = 'shown'
        self.step(HEALTHY)
        self.assertEqual(scheduled.session_notice(self.state), '')


class IssuesTest(unittest.TestCase):
    """issues() and decide() on the shapes doctor and sync print for each kind."""

    def test_task_and_validity_counts_and_their_read_errors(self):
        doctor = {'status': 'needs_attention',
                  'task_completion': {'strict_issue_count': 3, 'strict_issues': [PRIVATE]},
                  'validity': {'ignored_rejection_count': 2, 'ignored_rejections': [PRIVATE]}}
        self.assertEqual(scheduled.issues(HEALTHY['sync'], doctor), {'task': 3, 'validity': 2})
        # doctor writes a zero count and the exception when the reader itself failed.
        broken = {'task_completion': {'strict_issue_count': 0, 'error': 'OSError: ' + PRIVATE},
                  'validity': {'ignored_rejection_count': 0, 'error': 'ValueError: x'}}
        self.assertEqual(scheduled.issues(HEALTHY['sync'], broken), {'task': 1, 'validity': 1})
        self.assertEqual(scheduled.issues(HEALTHY['sync'], {'task_completion': {'strict_issue_count': 0},
                                                            'validity': {'ignored_rejection_count': 0}}), {})
        text = scheduled.message('needs_attention', scheduled.issues(HEALTHY['sync'], doctor))
        self.assertEqual(text, 'Beyin: gorev kaydi sorunu (3), gecerlilik sorunu (2) - ayrinti: beyin.py doctor')

    def test_a_hook_error_file_counts_even_when_hook_paths_are_fine(self):
        doctor = {'hook_paths': {'status': 'ok'}, 'hook-error.json': {'at': 1.0, 'error': 'OSError'}}
        self.assertEqual(scheduled.issues(HEALTHY['sync'], doctor), {'hook': 1})
        self.assertEqual(scheduled.issues(HEALTHY['sync'], {'hook_paths': {'status': 'ok'}, 'hook-error.json': None}), {})

    def test_degraded_sync_counts_its_warnings(self):
        sync = {'status': 'degraded', 'conflicts': [], 'warnings': [{'source': PRIVATE}, {'source': 'b'}]}
        self.assertEqual(scheduled.issues(sync, {}), {'sync_degraded': 2})
        self.assertEqual(scheduled.issues({'status': 'degraded'}, {}), {'sync_degraded': 1})
        self.assertEqual(scheduled.message('needs_attention', {'sync_degraded': 2}),
                         'Beyin: sync uyarisi (2) - ayrinti: beyin.py doctor')

    def test_a_degraded_sync_alone_makes_a_run_need_attention(self):
        tmp = tempfile.TemporaryDirectory(prefix='v3-scheduled-issues-')
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        cli = root / 'fake/cli.py'
        cli.parent.mkdir()
        cli.write_text(FAKE_CLI, encoding='utf-8')
        (cli.parent / 'outputs.json').write_text(json.dumps({
            'sync': {'status': 'degraded', 'conflicts': [], 'warnings': [{'source': PRIVATE}]},
            'doctor': {'status': 'observed_metadata', 'hook-error.json': {'error': 'OSError'}}}), encoding='utf-8')
        record, code = scheduled.run(root / 'vault', root / 'state', cli)
        self.assertEqual((record['status'], record['issues'], code),
                         ('needs_attention', {'sync_degraded': 1, 'hook': 1}, 4))

    def test_an_unreadable_or_future_last_notified_at_reminds_instead_of_staying_silent(self):
        now = 1_800_000_000
        told = {'notified_status': 'needs_attention'}
        self.assertEqual(scheduled.decide(dict(told, last_notified_at=scheduled._utc(now - 86400)),
                                          'needs_attention', now), (None, False))
        for last in ('yesterday', '2026-13-45T99:00:00Z', scheduled._utc(now + 3 * 86400), 7, None):
            with self.subTest(last=last):
                previous = dict(told, last_notified_at=last) if last is not None else dict(told)
                self.assertEqual(scheduled.decide(previous, 'needs_attention', now), ('attention', True))


class NotifierTest(unittest.TestCase):
    """The platform commands, with the subprocess replaced: what would run, never a real toast."""

    def run_show(self, platform, returncode=0, error=None, which='/usr/bin/notify-send'):
        calls = []

        def fake(argv, **options):
            calls.append((argv, options))
            if error:
                raise error
            return subprocess.CompletedProcess(argv, returncode)
        with mock.patch.object(scheduled.subprocess, 'run', fake), \
                mock.patch.object(scheduled.shutil, 'which', lambda name: which):
            return scheduled.show('Beyin: sync cakismasi (2)', platform=platform), calls

    def test_windows_uses_powershell_toast_with_the_text_in_the_environment(self):
        result, calls = self.run_show('win32')
        self.assertEqual(result, 'shown')
        argv, options = calls[0]
        self.assertTrue(argv[0].lower().endswith(os.path.join('windowspowershell', 'v1.0', 'powershell.exe')))
        self.assertIn('ToastNotificationManager', argv[-1])
        self.assertNotIn('sync cakismasi', ' '.join(argv), 'the text is never part of the script')
        self.assertEqual(options['env']['BEYIN_NOTIFY_TEXT'], 'Beyin: sync cakismasi (2)')

    def test_macos_passes_the_text_as_an_argument(self):
        result, calls = self.run_show('darwin')
        self.assertEqual(result, 'shown')
        self.assertEqual(calls[0][0][:2], ['/usr/bin/osascript', '-e'])
        self.assertEqual(calls[0][0][-1], 'Beyin: sync cakismasi (2)')

    def test_linux_uses_notify_send_and_skips_when_it_is_missing(self):
        result, calls = self.run_show('linux')
        self.assertEqual((result, calls[0][0][0], calls[0][0][-1]),
                         ('shown', '/usr/bin/notify-send', 'Beyin: sync cakismasi (2)'))
        self.assertEqual(self.run_show('linux', which=None), ('unavailable', []))

    def test_a_refusing_or_missing_notifier_is_reported(self):
        self.assertEqual(self.run_show('darwin', returncode=1)[0], 'failed')
        self.assertEqual(self.run_show('darwin', error=FileNotFoundError())[0], 'unavailable')
        self.assertEqual(self.run_show('win32', error=subprocess.TimeoutExpired('x', 30))[0], 'failed')


class InstalledTest(unittest.TestCase):
    """Through a real install: the entry point's human mode and the session-start line."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='v3-scheduled-installed-')
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.vault, self.state = root / 'Örnek Beyin', root / 'state'
        self.vault.mkdir()
        self.env = inherited_env(BEYIN_V3_NO_SPAWN='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
        self.env.pop('BEYIN_V3_FILTER_HARNESS_TURNS', None)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/install_v3.py'), '--vault', str(self.vault),
                                 '--state', str(self.state)], capture_output=True, text=True, encoding='utf-8',
                                env=self.env, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)

    def session_start(self):
        payload = {'hook_event_name': 'SessionStart', 'session_id': 's1', 'event_id': 's1-1', 'cwd': str(self.vault)}
        result = subprocess.run([sys.executable, str(self.vault / '.claude/scripts/beyin_v3_hook.py'), '--vault',
                                 str(self.vault), '--state', str(self.state), '--harness', 'claude'],
                                input=json.dumps(payload), capture_output=True, text=True, encoding='utf-8',
                                env=self.env, cwd=self.vault, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_human_mode_says_attention_and_the_session_says_an_unshown_notice_once(self):
        (self.vault / 'a.md').write_text('---\n{"id": "dup"}\n---\nOne.\n', encoding='utf-8')
        (self.vault / 'b.md').write_text('---\n{"id": "dup"}\n---\nTwo.\n', encoding='utf-8')
        ran = subprocess.run([sys.executable, str(self.vault / 'beyin.py'), 'scheduled-check', '--human'],
                             capture_output=True, text=True, encoding='utf-8', env=self.env, cwd=self.vault, timeout=300)
        self.assertEqual(ran.returncode, 4, ran.stdout + ran.stderr)
        self.assertIn('kontrol gerektiren bir sorun var', ran.stdout + ran.stderr)
        self.assertNotIn('tamamlanamadi', ran.stdout + ran.stderr)
        self.assertNotIn('Zamanlanmis denetim', self.session_start())
        (self.state / 'scheduled-notice.json').write_text(json.dumps(
            {'schema': 1, 'at': '2026-01-01T00:00:00Z', 'text': 'Beyin: sync cakismasi (1) - ayrinti: beyin.py doctor'}),
            encoding='utf-8')
        self.assertIn('kullaniciya soyle: Beyin: sync cakismasi (1)', self.session_start())
        self.assertNotIn('Zamanlanmis denetim', self.session_start())


if __name__ == '__main__':
    unittest.main()
