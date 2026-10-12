"""Human entrypoint smoke: a novice sees an honest short status, tools retain JSON."""
import importlib.util
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from v3_package_helpers import install, isolated_env, run_python

ROOT = Path(__file__).resolve().parents[1]


class EntryPresentationTest(unittest.TestCase):
    def test_human_doctor_and_machine_doctor_report_unverified_install(self):
        with tempfile.TemporaryDirectory(prefix='v3-entry-test-') as t:
            root = Path(t);vault=root/'vault';vault.mkdir();state=root/'state';env=isolated_env(root/'home')
            installed=install(vault,state,env)
            self.assertEqual(installed.returncode,0,installed.stderr)
            machine=run_python(vault/'beyin.py',['doctor'],vault,env)
            self.assertEqual(machine.returncode,0,machine.stderr)
            self.assertEqual(json.loads(machine.stdout)['status'],'never_seen')
            human=run_python(vault/'beyin.py',['doctor','--human'],vault,env)
            self.assertEqual(human.returncode,0,human.stderr)
            text=human.stdout.decode('utf-8')
            self.assertIn('3.0.0',text)
            self.assertIn('oturum',text.lower())
            self.assertNotIn('"hook-health.json"',text)
            self.assertNotIn(str(state),text)

    def test_entry_in_memory_invocation_avoids_io_redirect(self):
        with tempfile.TemporaryDirectory(prefix='v3-entry-mem-') as t:
            root = Path(t); vault = root / 'vault'; vault.mkdir(); state = root / 'state'; env = isolated_env(root / 'home')
            installed = install(vault, state, env)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            # Verify entrypoint runs cleanly in human mode with zero stdout-capture overhead
            human = run_python(vault / 'beyin.py', ['sync', '--human'], vault, env)
            self.assertEqual(human.returncode, 0, human.stderr)
            self.assertIn('succeeded', human.stdout.decode('utf-8').lower())

    def test_human_mode_prints_unshaped_results_and_shows_usage_errors(self):
        with tempfile.TemporaryDirectory(prefix='v3-entry-shape-') as t:
            root = Path(t); vault = root / 'vault'; vault.mkdir(); state = root / 'state'; env = isolated_env(root / 'home')
            (vault / 'Synthetic.md').write_text('# Synthetic\n\nQuartz shape canary.\n', encoding='utf-8')
            installed = install(vault, state, env)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            found = run_python(vault / 'beyin.py', ['context', 'Quartz shape canary', '--json'], vault, env)
            self.assertEqual(found.returncode, 0, found.stderr)
            record = next(r['id'] for r in json.loads(found.stdout)['records'] if r['source'] == 'Synthetic.md')
            # history returns a list, which human_result cannot shape: it prints as JSON, as before.
            human = run_python(vault / 'beyin.py', ['history', record, '--human'], vault, env)
            self.assertEqual(human.returncode, 0, human.stderr.decode('utf-8', errors='replace'))
            self.assertEqual(json.loads(human.stdout)[0]['record_id'], record)
            # An argparse error is no longer swallowed by the captured stderr in human mode.
            usage = run_python(vault / 'beyin.py', ['receipt', '--event-id', 'x', '--human'], vault, env)
            self.assertEqual(usage.returncode, 2)
            self.assertIn('--summary or --summary-file is required', usage.stderr.decode('utf-8'))


# The installer pins a resolved absolute path; this is one another OS wrote into a synced vault (#249).
FOREIGN_PIN = ('/home/ada/.local/state/beyin-v3/ab12' if sys.platform == 'win32' else
               chr(92).join(('C:', 'Users', 'ada', 'AppData', 'Local', 'beyin-v3', 'ab12')))


def pin(vault, value):
    path = vault / '.beyin-runtime.json'
    data = json.loads(path.read_text(encoding='utf-8'))
    data['state'] = value
    path.write_text(json.dumps(data), encoding='utf-8')


def codes(location):
    return [warning.split(':', 1)[0] for warning in location['warnings']]


class CrossPlatformPinTest(unittest.TestCase):
    """A runtime pin from another OS (#249): beyin.py uses this machine's default state, a reinstall repins."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='v3-cross-pin-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.vault, self.state = self.root / 'vault', self.root / 'state'
        self.vault.mkdir()
        self.env = isolated_env(self.root / 'home')
        installed = install(self.vault, self.state, self.env)
        self.assertEqual(installed.returncode, 0, installed.stderr)

    def test_foreign_pin_reads_the_default_state_and_doctor_names_it(self):
        pin(self.vault, FOREIGN_PIN)
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()
        for cwd in (self.vault, elsewhere):
            doctor = run_python(self.vault / 'beyin.py', ['doctor'], cwd, self.env)
            self.assertEqual(doctor.returncode, 0, doctor.stderr)
            location = json.loads(doctor.stdout)['state_location']
            self.assertIn('pinned_state_not_absolute', codes(location))
            # This machine's default state lives under the isolated home, not under the working directory.
            effective = Path(location['effective_state'])
            self.assertIn(self.root / 'home', effective.parents)
        synced = run_python(self.vault / 'beyin.py', ['sync'], elsewhere, self.env)
        self.assertEqual(synced.returncode, 0, synced.stderr)
        # Read as a relative path the pin used to become a state directory under the working directory.
        self.assertEqual(list(elsewhere.iterdir()), [])
        human = run_python(self.vault / 'beyin.py', ['doctor', '--human'], elsewhere, self.env)
        self.assertEqual(human.returncode, 0, human.stderr)
        self.assertIn('mutlak bir yol degil', human.stdout.decode('utf-8'))

    @unittest.skipIf(sys.platform == 'win32', 'a colon is not a valid Windows path character')
    def test_absolute_posix_pin_with_colon_and_backslash_is_used_as_is(self):
        vault, state = self.root / 'other-vault', self.root / ('st:a' + chr(92) + 'te')
        vault.mkdir()
        installed = install(vault, state, self.env)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        doctor = run_python(vault / 'beyin.py', ['doctor'], vault, self.env)
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        location = json.loads(doctor.stdout)['state_location']
        self.assertEqual(location['effective_state'], str(state))
        self.assertEqual(location['warnings'], [])

    def test_reinstall_replaces_a_foreign_pin_and_keeps_protecting_an_edited_one(self):
        pin(self.vault, FOREIGN_PIN)
        installed = install(self.vault, self.state, self.env)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        runtime = json.loads((self.vault / '.beyin-runtime.json').read_text(encoding='utf-8'))
        self.assertEqual(runtime['state'], str(self.state.resolve()))
        pin(self.vault, str(self.root / 'moved-state'))
        refused = install(self.vault, self.state, self.env)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn('Reinstall conflict: managed file changed .beyin-runtime.json', refused.stderr.decode('utf-8'))

    def test_same_os_foreign_user_pin_uses_this_machine_default_state(self):
        if sys.platform != 'win32':
            self.skipTest('The regression is Windows user-profile path portability')
        expected = Path(self.env['LOCALAPPDATA']) / 'beyin-v3' / hashlib.sha256(
            str(self.vault.resolve()).encode()).hexdigest()[:16]
        foreign = self.root / 'other-user' / 'localappdata' / 'beyin-v3' / expected.name
        pin(self.vault, str(foreign))
        doctor = run_python(self.vault / 'beyin.py', ['doctor'], self.vault, self.env)
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        location = json.loads(doctor.stdout)['state_location']
        self.assertEqual(Path(location['effective_state']).resolve(), expected.resolve())
        self.assertIn('effective_state_differs', codes(location))

    def test_resolve_state_across_linux_macos_and_windows(self):
        spec = importlib.util.spec_from_file_location('v3_cli_entry_test', ROOT / 'scripts/beyin_v3.py')
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        expected = cli.default_state(self.vault).resolve()
        key = expected.name

        # Foreign Windows pin
        win_pin = Path(r"C:\Users\other\AppData\Local\beyin-v3") / key
        self.assertEqual(cli.resolve_state(self.vault, win_pin), expected)

        # Foreign Linux pin
        linux_pin = Path(f"/home/other/.local/state/beyin-v3/{key}")
        self.assertEqual(cli.resolve_state(self.vault, linux_pin), expected)

        # Foreign macOS pin
        mac_pin = Path(f"/Users/other/Library/Application Support/beyin-v3/{key}")
        self.assertEqual(cli.resolve_state(self.vault, mac_pin), expected)

        # Explicit custom state is preserved
        custom = (self.root / "custom-state").resolve()
        self.assertEqual(cli.resolve_state(self.vault, custom), custom)
        changed_key = 'fedcba9876543210'
        self.assertEqual(cli.resolve_state(self.vault, Path('/home/foreign/.local/state/beyin-v3/' + changed_key)), expected)
        custom_layout = self.root.resolve() / 'state/beyin-v3' / expected.name
        self.assertEqual(cli.resolve_state(self.vault, custom_layout), custom_layout)
        previous_local = expected.parent / changed_key
        self.assertEqual(cli.resolve_state(self.vault, previous_local), previous_local)

    def test_only_the_pin_may_differ(self):
        spec = importlib.util.spec_from_file_location('install_v3_cross_pin', ROOT / 'scripts/install_v3.py')
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        baseline = json.dumps({'state': str(self.state.resolve()), 'schema': 1}).encode()
        def same(data):
            return installer.semantic_unchanged('.beyin-runtime.json', baseline, json.dumps(data).encode(), [])
        self.assertTrue(same({'state': FOREIGN_PIN, 'schema': 1}))
        self.assertFalse(same({'state': FOREIGN_PIN, 'schema': 2}))
        self.assertFalse(same({'state': FOREIGN_PIN, 'schema': 1, 'extra': True}))
        self.assertFalse(same({'state': str(self.root / 'moved-state'), 'schema': 1}))
        self.assertFalse(same({'schema': 1}))


if __name__ == '__main__':
    unittest.main()
