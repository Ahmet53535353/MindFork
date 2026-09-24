"""Transaction containment when the state root resolves differently once it exists (PR #97).

Windows returns a path that does not exist yet from Path.resolve() unchanged and applies a
redirect (an MSIX-virtualised %LOCALAPPDATA%, a junction, a moved folder) only once the
directory exists. The installer resolves its state root before creating it, so the
transaction must compare both sides as they resolve at write time. These tests reproduce
that sequence on every platform with a directory link created at the moment the state
directory is made, and pin that resolving the root never admits a real escape.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from v3_package_helpers import INSTALLER, ROOT, isolated_env

MODULE = ROOT / 'template/.claude/scripts/beyin_v3_update.py'


def link_directory(target, link, kind='any'):
    """Create a directory symlink or, on Windows, a junction; return the kind that worked."""
    if kind in ('any', 'symlink'):
        try:
            os.symlink(target, link, target_is_directory=True)
            return 'symlink'
        except (OSError, NotImplementedError):
            if kind == 'symlink':
                return None
    if os.name == 'nt':
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
            return 'junction'
        except (ImportError, AttributeError, OSError):
            pass
    return None


# Runs the real installer CLI; creating the state directory yields a redirect, as MSIX does.
DRIVER = """
import os, pathlib, runpy, sys
tests, state, target, installer, kind = sys.argv[1:6]
sys.path.insert(0, tests)
from v3_transaction_root_test import link_directory
original = pathlib.Path.mkdir
def mkdir(self, mode=0o777, parents=False, exist_ok=False):
    if os.path.abspath(self) == os.path.abspath(state) and not os.path.lexists(self):
        original(pathlib.Path(target), mode=mode, parents=True, exist_ok=True)
        if link_directory(target, state, kind) != kind:
            raise SystemExit(77)
        return
    return original(self, mode=mode, parents=parents, exist_ok=exist_ok)
pathlib.Path.mkdir = mkdir
sys.argv = [installer] + sys.argv[6:]
runpy.run_path(installer, run_name='__main__')
"""


def load_updater():
    spec = importlib.util.spec_from_file_location('beyin_v3_update_root_test_subject', MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TransactionRootTest(unittest.TestCase):
    def setUp(self):
        self.updater = load_updater()
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-transaction-root-')
        self.addCleanup(self.tmp.cleanup)
        # Resolve the fixture base first so the only alias under test is the one made here.
        self.base = Path(self.tmp.name).resolve()
        self.vault = self.base / 'Synthetic Vault Ölçüm'
        self.vault.mkdir()
        self.outside = self.base / 'outside'
        self.outside.mkdir()
        (self.outside / 'beyin.py').write_text('outside the vault\n', encoding='utf-8')

    def link(self, target, link, kind='any'):
        made = link_directory(target, link, kind)
        if made is None:
            self.skipTest('directory links unavailable on this runner')
        return made

    def redirected_state(self):
        """A state path that is plain before it exists and an alias afterwards."""
        local = self.base / 'Local'
        local.mkdir()
        return local / 'beyin-state', self.base / 'LocalCache' / 'Local' / 'beyin-state'

    def test_stale_state_root_accepts_targets_inside_its_redirected_location(self):
        state, target = self.redirected_state()
        target.mkdir(parents=True)
        self.link(target, state)
        (target / 'v3-install.json').write_text('{}\n', encoding='utf-8')
        for name in ('v3-install.json', 'update-journal.json'):
            with self.subTest(name=name):
                operation = {'scope': 'state', 'name': name}
                self.assertEqual(self.updater._destination(self.vault, state, operation), state / name)

    def test_links_inside_either_root_that_leave_it_are_still_rejected(self):
        state, target = self.redirected_state()
        target.mkdir(parents=True)
        self.link(target, state)
        kinds = ['symlink'] + (['junction'] if os.name == 'nt' else [])
        for kind in kinds:
            vault_link, state_link = self.vault / ('.claude-' + kind), target / ('escape-' + kind)
            if link_directory(self.outside, vault_link, kind) is None or link_directory(self.outside, state_link, kind) is None:
                continue
            cases = [(self.vault, 'vault', vault_link.name + '/beyin.py'),
                     (state, 'state', state_link.name + '/v3-install.json'),
                     (state.resolve(), 'state', state_link.name + '/v3-install.json')]
            for root, scope, name in cases:
                with self.subTest(kind=kind, root=str(root), name=name):
                    with self.assertRaisesRegex(ValueError, 'transaction target escapes root'):
                        self.updater._destination(self.vault, root, {'scope': scope, 'name': name})
        leaf = self.vault / 'beyin.py'
        try:
            os.symlink(self.outside / 'beyin.py', leaf)
        except (OSError, NotImplementedError):
            return
        with self.assertRaisesRegex(ValueError, 'transaction target escapes root'):
            self.updater._destination(self.vault, self.vault, {'scope': 'vault', 'name': 'beyin.py'})

    def test_parent_and_absolute_names_are_rejected_before_any_resolution(self):
        names = ['../outside/beyin.py', '.claude/../../outside/beyin.py', str(self.outside / 'beyin.py')]
        for name in names:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, 'unsafe transaction path'):
                    self.updater._destination(self.vault, self.vault, {'scope': 'vault', 'name': name})
        if os.name == 'nt':
            # Rooted and drive-relative names are not absolute on Windows; containment catches them.
            drive = next(letter for letter in 'ZYX' if not str(self.vault).upper().startswith(letter))
            for name in ('\\outside\\beyin.py', drive + ':beyin.py'):
                with self.subTest(name=name):
                    with self.assertRaises(ValueError):
                        self.updater._destination(self.vault, self.vault, {'scope': 'vault', 'name': name})

    def test_install_completes_when_creating_the_state_directory_makes_a_redirect(self):
        state, target = self.redirected_state()
        probe = self.base / 'probe'
        kind = self.link(self.outside, probe)
        driver = self.base / 'redirect_driver.py'
        driver.write_text(DRIVER, encoding='utf-8')
        env = isolated_env(self.base / 'home')
        result = subprocess.run([sys.executable, str(driver), str(Path(__file__).resolve().parent), str(state),
                                 str(target), str(INSTALLER), kind,
                                 '--vault', str(self.vault), '--state', str(state)],
                                cwd=ROOT, env=env, capture_output=True, timeout=120)
        if result.returncode == 77:
            self.skipTest('directory link could not be created by the installer driver')
        stderr = result.stderr.decode('utf-8', errors='replace')
        self.assertEqual(result.returncode, 0, stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'installed')
        self.assertEqual(os.path.realpath(state), os.path.realpath(target), 'the fixture must have redirected')
        self.assertTrue((self.vault / '.beyin-version').read_text(encoding='utf-8').strip())
        self.assertTrue((target / 'v3-install.json').is_file())
        self.assertFalse((target / 'update-journal.json').exists(), 'no half-applied transaction left behind')
        self.assertEqual(sorted(p.name for p in self.outside.iterdir()), ['beyin.py'])


if __name__ == '__main__':
    unittest.main()
