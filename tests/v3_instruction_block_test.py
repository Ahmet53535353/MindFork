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

    def install(self):
        return self.run_cli(ROOT / 'scripts/install_v3.py', '--vault', self.vault, '--state', self.state)

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
        self.install()
        for name in ('AGENTS.md', 'CLAUDE.md'):
            with self.subTest(file=name):
                block = self.block(name)
                self.assertIn(' '.join(ENGLISH.split()), ' '.join(block.split()))
                self.assertIn(' '.join(TURKISH.split()), ' '.join(block.split()))

    def test_reinstall_over_previous_block_adopts_the_clause_and_keeps_user_text(self):
        self.install()
        self.downgrade()
        self.install()
        for name in ('AGENTS.md', 'CLAUDE.md'):
            self.assertIn(' '.join(ENGLISH.split()), ' '.join(self.block(name).split()))
        self.assertIn(NOTE.strip(), (self.vault / 'AGENTS.md').read_text(encoding='utf-8'))

    def test_crlf_router_with_user_text_outside_the_block_still_reinstalls(self):
        self.install()
        self.downgrade()
        path = self.vault / 'AGENTS.md'
        path.write_bytes(path.read_bytes().replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
        self.install()
        self.assertIn(' '.join(ENGLISH.split()), ' '.join(self.block().split()))
        self.assertIn(NOTE.strip(), path.read_text(encoding='utf-8'))

    def test_update_and_rollback_over_previous_block_keep_working(self):
        self.install()
        self.downgrade()
        package = self.base / 'upgrade.zip'
        self.run_cli(ROOT / 'scripts/build_v3_release.py', '--output', package, '--version', '3.0.3')
        self.assertEqual(self.run_cli(self.vault / 'beyin.py', 'update', '--package', package)['version'], '3.0.3')
        for name in ('AGENTS.md', 'CLAUDE.md'):
            self.assertIn(' '.join(TURKISH.split()), ' '.join(self.block(name).split()))
        self.assertIn(NOTE.strip(), (self.vault / 'AGENTS.md').read_text(encoding='utf-8'))
        self.assertEqual(self.run_cli(self.vault / 'beyin.py', 'rollback')['status'], 'rolled_back')
        for name in ('AGENTS.md', 'CLAUDE.md'):
            self.assertNotIn(' '.join(TURKISH.split()), ' '.join(self.block(name).split()))
        self.assertIn(NOTE.strip(), (self.vault / 'AGENTS.md').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
