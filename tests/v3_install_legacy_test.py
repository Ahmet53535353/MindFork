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
CUSTOM_HOOK = b'#!/bin/sh\n# kullanicinin kendi session-end kancasi\nexit 0\n'


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
        extracted = self.base / 'extracted'
        with zipfile.ZipFile(build_package(self.base / 'release.zip', '3.0.1', self.env)) as archive:
            # The pre-#40 validator only accepts this key (issue #73).
            self.assertEqual(set(json.loads(archive.read('manifest.json'))['legacy_skill_hashes']),
                             {'.claude/skills/beyin-doktor/SKILL.md'})
            archive.extractall(extracted)
        for tag in TAGS:
            with self.subTest(tag=tag):
                self.new_vault('package-' + tag)
                seeded = {}
                for name in SKILLS:
                    data = (RELEASED / tag / (name + '.md')).read_bytes()
                    for root in ROOTS:
                        relative = root + '/skills/' + name + '/SKILL.md'
                        seeded[relative] = self.seed(relative, data)
                result = run_python(extracted / 'scripts/install_v3.py',
                                    ['--vault', self.vault, '--state', self.state], extracted, self.env)
                self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
                for relative, path in seeded.items():
                    self.assertEqual(path.read_bytes(),
                                     (ROOT / 'template/.agents/skills' / relative.split('/')[2] / 'SKILL.md').read_bytes())

    def test_legacy_wire_subset_preserves_custom_skill_conflict(self):
        doctor = '.claude/skills/beyin-doktor/SKILL.md'
        subset = {doctor: self.installer.default_skill_hashes()[doctor]}
        for root in ROOTS:
            for name in SKILLS:
                with self.subTest(root=root, skill=name):
                    relative = root + '/skills/' + name + '/SKILL.md'
                    path = self.seed(relative, (RELEASED / 'v3.0.2' / (name + '.md')).read_bytes()
                                     + b'\nUser customization.\n')
                    before = snapshot(self.vault)
                    with self.assertRaisesRegex(ValueError, 'Unmanaged file conflict'):
                        self.installer.install(self.vault, self.state, plan_only=True,
                                               legacy_skill_hashes=subset)
                    self.assertEqual(snapshot(self.vault), before)
                    path.unlink()

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

    def test_kept_customized_runner_is_untouched_unplanned_and_unmanaged(self):
        runner = self.seed('.claude/scripts/flush.py', CUSTOM_RUNNER)
        result = self.cli('--keep-customized-legacy', '.claude\\scripts\\flush.py')
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        self.assertEqual(runner.read_bytes(), CUSTOM_RUNNER)
        self.assertEqual(json.loads(result.stdout)['kept_legacy'], ['.claude/scripts/flush.py'])
        manifest = json.loads((self.state / 'v3-install.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['kept_legacy'], ['.claude/scripts/flush.py'])
        self.assertNotIn('.claude/scripts/flush.py', manifest['files'])

    def test_keeping_one_runner_does_not_exempt_another(self):
        self.seed('.claude/scripts/flush.py', CUSTOM_RUNNER)
        self.seed('.claude/scripts/compile.py', CUSTOM_RUNNER)
        with self.assertRaises(ValueError) as raised:
            self.installer.install(self.vault, self.state, plan_only=True,
                                   keep_customized=('.claude/scripts/flush.py',))
        self.assertIn('Customized legacy runner requires review .claude/scripts/compile.py',
                      str(raised.exception))

    def test_keeping_a_path_outside_the_legacy_runner_set_is_rejected(self):
        self.seed('notes/rapor.md', b'Kullanici notu.\n')
        for name in ('notes/rapor.md', '.claude/skills/beyin/SKILL.md', '../escape.py',
                     '.claude/scripts/beyin_v3_cli.py'):
            with self.subTest(path=name):
                with self.assertRaises(ValueError) as raised:
                    self.installer.install(self.vault, self.state, plan_only=True,
                                           keep_customized=(name,))
                self.assertIn('unsupported legacy managed path', str(raised.exception))
        result = self.cli('--keep-customized-legacy', 'notes/rapor.md')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.vault / 'beyin.py').exists())

    def test_one_runner_cannot_be_both_kept_and_retired(self):
        runner = self.seed('.claude/scripts/flush.py', CUSTOM_RUNNER)
        with self.assertRaises(ValueError) as raised:
            self.installer.install(self.vault, self.state, plan_only=True,
                                   accept_customized=('.claude/scripts/flush.py',),
                                   keep_customized=('.claude/scripts/flush.py',))
        self.assertIn('both kept and retired', str(raised.exception))
        result = self.cli('--accept-customized-legacy', '.claude/scripts/flush.py',
                          '--keep-customized-legacy', '.claude/scripts/flush.py')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(runner.read_bytes(), CUSTOM_RUNNER)

    def test_plan_reports_the_kept_runner_outside_write_retire_and_preserve(self):
        runner = self.seed('.claude/scripts/flush.py', CUSTOM_RUNNER)
        self.state.mkdir(parents=True, exist_ok=True)
        before_vault, before_state = snapshot(self.vault), snapshot(self.state)
        result = self.cli('--plan', '--keep-customized-legacy', '.claude/scripts/flush.py')
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        plan = json.loads(result.stdout)
        self.assertEqual(plan['status'], 'plan')
        self.assertEqual(plan['keep'], ['.claude/scripts/flush.py'])
        for section in ('write', 'retire', 'preserve'):
            self.assertNotIn('.claude/scripts/flush.py', plan[section], section)
        self.assertIn('beyin.py', plan['write'])
        self.assertEqual(snapshot(self.vault), before_vault)
        self.assertEqual(snapshot(self.state), before_state)
        self.assertEqual(runner.read_bytes(), CUSTOM_RUNNER)

    def test_hook_entries_of_a_kept_hook_survive_while_others_are_stripped(self):
        hook = self.seed('.claude/hooks/session-end.sh', CUSTOM_HOOK)
        entries = {'hooks': {'SessionEnd': [{'hooks': [
            {'type': 'command', 'command': '"$CLAUDE_PROJECT_DIR/.claude/hooks/session-end.sh"'},
            {'type': 'command', 'command': '"$CLAUDE_PROJECT_DIR/.claude/hooks/session-start.sh"'},
            {'type': 'command', 'command': 'synthetic-custom-command'}]}]}}
        names = ('.claude/settings.json', '.claude/settings.local.json', '.codex/hooks.json')
        for name in names:
            self.seed(name, json.dumps(entries).encode('utf-8'))
        result = self.cli('--keep-customized-legacy', '.claude/hooks/session-end.sh')
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        self.assertEqual(hook.read_bytes(), CUSTOM_HOOK)
        for name in names:
            with self.subTest(settings=name):
                text = (self.vault / name).read_text(encoding='utf-8')
                self.assertIn('.claude/hooks/session-end.sh', text)
                self.assertNotIn('session-start.sh', text)
                self.assertIn('synthetic-custom-command', text)

    def test_update_without_the_flag_honours_the_kept_runner_from_the_manifest(self):
        runner = self.seed('.claude/scripts/flush.py', CUSTOM_RUNNER)
        result = self.cli('--keep-customized-legacy', '.claude/scripts/flush.py')
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        package = build_package(self.base / 'upgrade.zip', '3.0.1', self.env)
        update = run_python(self.vault / 'beyin.py', ['update', '--package', package], self.vault, self.env)
        self.assertEqual(update.returncode, 0, update.stderr.decode('utf-8', errors='replace'))
        self.assertEqual(runner.read_bytes(), CUSTOM_RUNNER)
        self.assertEqual((self.vault / '.beyin-version').read_text(encoding='utf-8').strip(), '3.0.1')
        manifest = json.loads((self.state / 'v3-install.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['kept_legacy'], ['.claude/scripts/flush.py'])

    def test_uninstall_leaves_the_kept_runner_and_its_hook_entry_alone(self):
        runner = self.seed('.claude/scripts/flush.py', CUSTOM_RUNNER)
        hook = self.seed('.claude/hooks/session-end.sh', CUSTOM_HOOK)
        settings = self.seed('.claude/settings.json', json.dumps({'hooks': {'SessionEnd': [{'hooks': [
            {'type': 'command', 'command': '"$CLAUDE_PROJECT_DIR/.claude/hooks/session-end.sh"'}]}]}}).encode('utf-8'))
        result = self.cli('--keep-customized-legacy', '.claude/scripts/flush.py',
                          '--keep-customized-legacy', '.claude/hooks/session-end.sh')
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        uninstall = self.cli('--uninstall')
        self.assertEqual(uninstall.returncode, 0, uninstall.stderr.decode('utf-8', errors='replace'))
        self.assertEqual(runner.read_bytes(), CUSTOM_RUNNER)
        self.assertEqual(hook.read_bytes(), CUSTOM_HOOK)
        self.assertIn('.claude/hooks/session-end.sh', settings.read_text(encoding='utf-8'))

    def test_doctor_reports_the_kept_legacy_runners(self):
        self.seed('.claude/scripts/flush.py', CUSTOM_RUNNER)
        result = self.cli('--keep-customized-legacy', '.claude/scripts/flush.py')
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        doctor = run_python(self.vault / 'beyin.py', ['doctor'], self.vault, self.env)
        self.assertEqual(doctor.returncode, 0, doctor.stderr.decode('utf-8', errors='replace'))
        self.assertEqual(json.loads(doctor.stdout)['kept_legacy_runners'], ['.claude/scripts/flush.py'])
        self.new_vault('plain')
        plain = self.cli()
        self.assertEqual(plain.returncode, 0, plain.stderr.decode('utf-8', errors='replace'))
        plain_doctor = run_python(self.vault / 'beyin.py', ['doctor'], self.vault, self.env)
        self.assertEqual(plain_doctor.returncode, 0, plain_doctor.stderr.decode('utf-8', errors='replace'))
        self.assertEqual(json.loads(plain_doctor.stdout)['kept_legacy_runners'], [])


if __name__ == '__main__':
    unittest.main()
