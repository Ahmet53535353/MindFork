"""The generated AGENTS.md block must separate direct user statements from agent inferences."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('BEYIN_TEST_REPO', Path(__file__).resolve().parents[1]))
START, END = '<!-- beyin-v3:start -->', '<!-- beyin-v3:end -->'
ENGLISH = ('A preference, decision or fact the user states directly is not an inference; '
           'record it promptly without waiting to be asked.')
TURKISH = ('Kullanıcının doğrudan söylediği tercih, karar ve olgu çıkarım değildir; '
           'istenmesini beklemeden kaydedilir.')
NOTE = '\nKullanıcının kendi notu: bu paragraf blok dışında ve korunmalı.\n'
RULES = '# Kurallarım\nUSER_RULE_SENTINEL: yalnız AGENTS.md içinde yaşar.\n'
CLAUDE = '# Claude kuralları\nBu dosya kendi talimatlarını taşır.\n'
IMPORT = b'@AGENTS.md\n'


class InstructionBlockTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='beyin-instruction-block-')
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.vault = self.base / 'Örnek Beyin'
        self.vault.mkdir()
        self.state = self.base / 'state'
        self.env = dict(os.environ, BEYIN_V3_NO_SPAWN='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')

    def run_cli(self, script, *args):
        result = subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True,
                                text=True, encoding='utf-8', env=self.env, cwd=self.vault, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def install(self, *extra):
        return self.run_cli(ROOT / 'scripts/install_v3.py', '--vault', self.vault, '--state', self.state, *extra)

    def install_conflict(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/install_v3.py'), '--vault', str(self.vault),
                                 '--state', str(self.state)], capture_output=True, text=True, encoding='utf-8',
                                env=self.env, cwd=self.vault, timeout=120)
        self.assertEqual(result.returncode, 1, result.stdout)
        return json.loads(result.stderr)['message']

    def seed(self, name, text):
        (self.vault / name).write_bytes(text.encode())
        return text.encode()

    def manifest(self):
        return json.loads((self.state / 'v3-install.json').read_text(encoding='utf-8'))

    def as_previous_install(self, original):
        """Leave CLAUDE.md and its manifest entry exactly as the pre-#84 installer did."""
        data = ((original or '').rstrip() + '\n\n' + START + self.block() + END + '\n').encode()
        (self.vault / 'CLAUDE.md').write_bytes(data)
        manifest = self.manifest()
        manifest['files']['CLAUDE.md'] = {
            'original': base64.b64encode(original.encode()).decode() if original is not None else None,
            'installed_hash': hashlib.sha256(data).hexdigest(), 'installed_content': base64.b64encode(data).decode()}
        (self.state / 'v3-install.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return data

    def update(self):
        package = self.base / 'upgrade.zip'
        if not package.exists():
            self.run_cli(ROOT / 'scripts/build_v3_release.py', '--output', package, '--version', '3.0.3')
        self.assertEqual(self.run_cli(self.vault / 'beyin.py', 'update', '--package', package)['version'], '3.0.3')

    def block(self, name='AGENTS.md'):
        text = (self.vault / name).read_text(encoding='utf-8')
        return text.split(START)[1].split(END)[0]

    def downgrade(self):
        """Rewrite both routers as a vault installed before this clause existed."""
        manifest_path = self.state / 'v3-install.json'
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        for name in ('AGENTS.md', 'CLAUDE.md'):
            path = self.vault / name
            text = path.read_text(encoding='utf-8')
            for sentence in (ENGLISH, TURKISH):
                pattern = r'\s*' + r'\s+'.join(map(re.escape, sentence.split()))
                text, count = re.subn(pattern, '', text, count=1)
                self.assertEqual(count, 1, 'clause missing from generated ' + name)
            data = text.encode()
            manifest['files'][name] = dict(manifest['files'][name], installed_hash=hashlib.sha256(data).hexdigest(),
                                           installed_content=base64.b64encode(data).decode())
            # AGENTS.md also carries a paragraph the user added after that install, so its hash
            # cannot match and the reinstall gate has to fall through to the block comparison.
            path.write_text(text + NOTE if name == 'AGENTS.md' else text, encoding='utf-8')
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def test_generated_block_records_direct_user_statements_in_both_languages(self):
        self.seed('CLAUDE.md', CLAUDE)
        self.install()
        for name in ('AGENTS.md', 'CLAUDE.md'):
            with self.subTest(file=name):
                block = self.block(name)
                self.assertIn(' '.join(ENGLISH.split()), ' '.join(block.split()))
                self.assertIn(' '.join(TURKISH.split()), ' '.join(block.split()))

    def test_reinstall_over_previous_block_adopts_the_clause_and_keeps_user_text(self):
        self.seed('CLAUDE.md', CLAUDE)
        self.install()
        self.downgrade()
        self.install()
        for name in ('AGENTS.md', 'CLAUDE.md'):
            self.assertIn(' '.join(ENGLISH.split()), ' '.join(self.block(name).split()))
        self.assertIn(NOTE.strip(), (self.vault / 'AGENTS.md').read_text(encoding='utf-8'))

    def test_crlf_router_with_user_text_outside_the_block_still_reinstalls(self):
        self.seed('CLAUDE.md', CLAUDE)
        self.install()
        self.downgrade()
        path = self.vault / 'AGENTS.md'
        path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
        self.install()
        self.assertIn(' '.join(ENGLISH.split()), ' '.join(self.block().split()))
        self.assertIn(NOTE.strip(), path.read_text(encoding='utf-8'))

    def test_update_and_rollback_over_previous_block_keep_working(self):
        self.seed('CLAUDE.md', CLAUDE)
        self.install()
        self.downgrade()
        self.update()
        for name in ('AGENTS.md', 'CLAUDE.md'):
            self.assertIn(' '.join(TURKISH.split()), ' '.join(self.block(name).split()))
        self.assertIn(NOTE.strip(), (self.vault / 'AGENTS.md').read_text(encoding='utf-8'))
        self.assertEqual(self.run_cli(self.vault / 'beyin.py', 'rollback')['status'], 'rolled_back')
        for name in ('AGENTS.md', 'CLAUDE.md'):
            self.assertNotIn(' '.join(TURKISH.split()), ' '.join(self.block(name).split()))
        self.assertIn(NOTE.strip(), (self.vault / 'AGENTS.md').read_text(encoding='utf-8'))

    def test_missing_claude_md_is_created_as_an_agents_md_import(self):
        rules = self.seed('AGENTS.md', RULES)
        self.install()
        self.assertEqual((self.vault / 'CLAUDE.md').read_bytes(), IMPORT)
        agents = (self.vault / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertIn('USER_RULE_SENTINEL', agents)
        self.assertEqual(agents.count(START), 1)
        self.assertIsNone(self.manifest()['files']['CLAUDE.md']['original'])
        self.install()
        self.assertEqual((self.vault / 'CLAUDE.md').read_bytes(), IMPORT)
        self.install('--uninstall')
        self.assertFalse((self.vault / 'CLAUDE.md').exists())
        self.assertEqual((self.vault / 'AGENTS.md').read_bytes(), rules)

    def test_claude_md_that_imports_agents_md_is_not_given_a_second_block(self):
        rules, claude = self.seed('AGENTS.md', RULES), self.seed('CLAUDE.md', CLAUDE + '\n@AGENTS.md\n')
        self.install()
        self.assertEqual((self.vault / 'CLAUDE.md').read_bytes(), claude)
        self.assertNotIn('CLAUDE.md', self.manifest()['files'])
        self.assertEqual((self.vault / 'AGENTS.md').read_text(encoding='utf-8').count(START), 1)
        self.install()
        self.install('--uninstall')
        self.assertEqual([(self.vault / name).read_bytes() for name in ('AGENTS.md', 'CLAUDE.md')], [rules, claude])

    def test_claude_md_without_import_keeps_its_own_block(self):
        claude = self.seed('CLAUDE.md', CLAUDE)
        self.install()
        text = (self.vault / 'CLAUDE.md').read_text(encoding='utf-8')
        self.assertTrue(text.startswith(CLAUDE))
        self.assertEqual(text.count(START), 1)
        self.install('--uninstall')
        self.assertEqual((self.vault / 'CLAUDE.md').read_bytes(), claude)

    def test_symlinked_router_is_written_once(self):
        for link, target in (('CLAUDE.md', 'AGENTS.md'), ('AGENTS.md', 'CLAUDE.md')):
            with self.subTest(link=link):
                self.vault, self.state = self.base / ('vault-' + link), self.base / ('state-' + link)
                self.vault.mkdir()
                rules = self.seed(target, RULES)
                try: (self.vault / link).symlink_to(target)
                except OSError: self.skipTest('symlink unavailable on host')
                self.install()
                self.install()
                self.assertTrue((self.vault / link).is_symlink())
                self.assertEqual(list(self.manifest()['files']).count(target), 1)
                self.assertNotIn(link, self.manifest()['files'])
                self.assertEqual((self.vault / target).read_text(encoding='utf-8').count(START), 1)
                self.install('--uninstall')
                self.assertTrue((self.vault / link).is_symlink())
                self.assertEqual((self.vault / target).read_bytes(), rules)

    def test_update_migrates_block_only_claude_md_from_previous_install(self):
        rules = self.seed('AGENTS.md', RULES)
        self.install()
        self.as_previous_install(None)
        self.update()
        self.assertEqual((self.vault / 'CLAUDE.md').read_bytes(), IMPORT)
        agents = (self.vault / 'AGENTS.md').read_text(encoding='utf-8')
        self.assertIn('USER_RULE_SENTINEL', agents)
        self.assertEqual(agents.count(START), 1)
        self.install('--uninstall')
        self.assertFalse((self.vault / 'CLAUDE.md').exists())
        self.assertEqual((self.vault / 'AGENTS.md').read_bytes(), rules)

    def test_update_drops_duplicate_block_from_importing_claude_md(self):
        original = CLAUDE + '\n@./AGENTS.md\n'
        rules, claude = self.seed('AGENTS.md', RULES), self.seed('CLAUDE.md', original)
        self.install()
        self.as_previous_install(original)
        self.update()
        self.assertEqual((self.vault / 'CLAUDE.md').read_bytes(), claude)
        self.assertEqual((self.vault / 'AGENTS.md').read_text(encoding='utf-8').count(START), 1)
        self.install('--uninstall')
        self.assertEqual([(self.vault / name).read_bytes() for name in ('AGENTS.md', 'CLAUDE.md')], [rules, claude])

    def test_block_removed_by_hand_from_importing_claude_md_is_not_a_conflict(self):
        original = CLAUDE + '\n@AGENTS.md\n'
        self.seed('CLAUDE.md', original)
        self.install()
        self.as_previous_install(original)
        edited = self.seed('CLAUDE.md', original + '\nKullanıcı bloğu elle kaldırdı.\n')
        self.install()
        self.assertEqual((self.vault / 'CLAUDE.md').read_bytes(), edited)

    def test_user_edits_to_claude_md_still_conflict_or_survive(self):
        self.install()
        path = self.vault / 'CLAUDE.md'
        path.write_bytes(b'# Kendi Claude dosyam, import yok\n')
        self.assertIn('Reinstall conflict: managed file changed CLAUDE.md', self.install_conflict())
        created = self.as_previous_install(None)
        edited = created.replace(b'## V3 companion', b'## Edited companion')
        path.write_bytes(edited)
        self.assertIn('Reinstall conflict: managed file changed CLAUDE.md', self.install_conflict())
        self.assertEqual(path.read_bytes(), edited)
        # Text the user added around the block is theirs: the block is refreshed, the file is not replaced.
        path.write_bytes(created + NOTE.encode())
        self.install()
        text = path.read_text(encoding='utf-8')
        self.assertIn(NOTE.strip(), text)
        self.assertEqual(text.count(START), 1)
        importing = self.seed('CLAUDE.md', CLAUDE + '\n@AGENTS.md\n\n' + START + '\nkullanıcı düzenlemesi\n' + END + '\n')
        self.assertIn('Reinstall conflict: managed file changed CLAUDE.md', self.install_conflict())
        self.assertEqual(path.read_bytes(), importing)


if __name__ == '__main__':
    unittest.main()
