"""A vault whose state manifest is gone must still reinstall, and a customized legacy runner
must be retirable through one named path instead of a blanket override."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from v3_package_helpers import ROOT, build_package, isolated_env, run_python, snapshot

RELEASED = Path(__file__).resolve().parent / 'fixtures/v3/released-skills'
TAGS = ('v3.0.0', 'v3.0.1', 'v3.0.2')
SKILLS = ('beyin', 'beyin-doktor', 'beyin-guncelle')
ROOTS = ('.agents', '.claude')
CUSTOM_RUNNER = b'# kullanicinin kendi flush surumu\nprint("synthetic customized legacy runner")\n'


class InstallLegacyExemptionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-install-legacy-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.env = isolated_env(self.base / 'home')
        spec = importlib.util.spec_from_file_location('beyin_legacy_installer', ROOT / 'scripts/install_v3.py')
        self.installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.installer)
        self.new_vault()

    def new_vault(self, label='vault'):
        self.vault = self.base / ('Örnek Beyin ' + label)
        self.vault.mkdir()
        self.state = self.base / ('state-' + label)
        return self.vault

    def seed(self, name, data):
        path = self.vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def cli(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts/install_v3.py'),
                               '--vault', str(self.vault), '--state', str(self.state), *args],
                              cwd=ROOT, env=self.env, capture_output=True, timeout=120)

    def test_released_starter_skills_at_both_roots_install_without_a_manifest(self):
        for tag in TAGS:
            with self.subTest(tag=tag):
                self.new_vault(tag)
                seeded = {}
                for name in SKILLS:
                    data = (RELEASED / tag / (name + '.md')).read_bytes()
                    for root in ROOTS:
                        seeded[root + '/skills/' + name + '/SKILL.md'] = self.seed(
                            root + '/skills/' + name + '/SKILL.md', data)
                self.installer.install(self.vault, self.state)
                for relative, path in seeded.items():
                    skill = relative.split('/')[2]
                    self.assertEqual(path.read_bytes(),
                                     (ROOT / 'template/.agents/skills' / skill / 'SKILL.md').read_bytes(),
                                     relative)

    def test_released_package_carries_the_exemption_for_both_roots(self):
        import zipfile
        data = (RELEASED / 'v3.0.0/beyin.md').read_bytes()
        for root in ROOTS:
            self.seed(root + '/skills/beyin/SKILL.md', data)
        extracted = self.base / 'extracted'
        with zipfile.ZipFile(build_package(self.base / 'release.zip', '3.0.1', self.env)) as archive:
            archive.extractall(extracted)
        result = run_python(extracted / 'scripts/install_v3.py',
                            ['--vault', self.vault, '--state', self.state], extracted, self.env)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))

    def test_stock_claude_doctor_skill_stays_exempt(self):
        path = self.seed('.claude/skills/beyin-doktor/SKILL.md',
                         (RELEASED / 'stock-claude-doctor.md').read_bytes())
        self.installer.install(self.vault, self.state)
        self.assertEqual(path.read_bytes(),
                         (ROOT / 'template/.agents/skills/beyin-doktor/SKILL.md').read_bytes())

    def test_unknown_skill_content_is_still_an_unmanaged_conflict(self):
        for root in ROOTS:
            for name in SKILLS:
                with self.subTest(root=root, skill=name):
                    relative = root + '/skills/' + name + '/SKILL.md'
                    path = self.seed(relative, b'Kullanicinin kendi ' + name.encode() + b' skilli.\n')
                    with self.assertRaises(ValueError) as raised:
                        self.installer.install(self.vault, self.state, plan_only=True)
                    self.assertEqual(str(raised.exception), 'Unmanaged file conflict ' + relative)
                    path.unlink()

    def test_customized_legacy_runner_needs_its_own_named_acceptance(self):
        runner = self.seed('.claude/scripts/flush.py', CUSTOM_RUNNER)
        with self.assertRaises(ValueError) as raised:
            self.installer.install(self.vault, self.state, plan_only=True)
        self.assertIn('Customized legacy runner requires review .claude/scripts/flush.py',
                      str(raised.exception))
        self.assertEqual(runner.read_bytes(), CUSTOM_RUNNER)
        result = self.cli('--accept-customized-legacy', '.claude/scripts/flush.py')
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        self.assertIn(b'BEYIN_V3_LEGACY_RETIRED', runner.read_bytes())
        uninstall = self.cli('--uninstall')
        self.assertEqual(uninstall.returncode, 0, uninstall.stderr.decode('utf-8', errors='replace'))
        self.assertEqual(runner.read_bytes(), CUSTOM_RUNNER)

    def test_accepting_one_runner_does_not_exempt_another(self):
        self.seed('.claude/scripts/flush.py', CUSTOM_RUNNER)
        self.seed('.claude/scripts/compile.py', CUSTOM_RUNNER)
        with self.assertRaises(ValueError) as raised:
            self.installer.install(self.vault, self.state, plan_only=True,
                                   accept_customized=('.claude/scripts/flush.py',))
        self.assertIn('Customized legacy runner requires review .claude/scripts/compile.py',
                      str(raised.exception))

    def test_acceptance_outside_the_legacy_runner_set_is_rejected(self):
        self.seed('notes/rapor.md', b'Kullanici notu.\n')
        for name in ('notes/rapor.md', '.claude/skills/beyin/SKILL.md', '../escape.py',
                     '.claude/scripts/beyin_v3_cli.py'):
            with self.subTest(path=name):
                with self.assertRaises(ValueError) as raised:
                    self.installer.install(self.vault, self.state, plan_only=True,
                                           accept_customized=(name,))
                self.assertIn('unsupported legacy managed path', str(raised.exception))
        result = self.cli('--accept-customized-legacy', 'notes/rapor.md')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.vault / 'beyin.py').exists())

    def test_plan_reports_the_retirement_and_writes_nothing(self):
        runner = self.seed('.claude/scripts/flush.py', CUSTOM_RUNNER)
        self.state.mkdir(parents=True, exist_ok=True)
        before_vault, before_state = snapshot(self.vault), snapshot(self.state)
        result = self.cli('--plan', '--accept-customized-legacy', '.claude/scripts/flush.py')
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        plan = json.loads(result.stdout)
        self.assertEqual(plan['status'], 'plan')
        self.assertEqual(plan['retire'], ['.claude/scripts/flush.py'])
        self.assertIn('.claude/scripts/flush.py', plan['preserve'])
        self.assertIn('beyin.py', plan['write'])
        self.assertNotIn('.claude/scripts/flush.py', plan['write'])
        self.assertEqual(snapshot(self.vault), before_vault)
        self.assertEqual(snapshot(self.state), before_state)
        self.assertEqual(runner.read_bytes(), CUSTOM_RUNNER)
        self.assertFalse((self.state / 'v3-install.json').exists())


if __name__ == '__main__':
    unittest.main()
