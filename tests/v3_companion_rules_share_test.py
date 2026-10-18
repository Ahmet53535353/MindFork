"""The number doctor promises about the rules must be the number the opening delivers.

Upstream's #374 test holds with six companion sources: the size the water-fill reserves for
Kurallar.md is also the size that arrives whole. This fork has a seventh source
(Tetikleyici.md) and its own floors, so the reservation and the whole-arrive size are not
the same by construction -- the promise has to be measured here, not assumed. Synthetic rules
only.
"""
import importlib.util
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

from v3_package_helpers import inherited_env

ROOT = Path(os.environ.get('BEYIN_TEST_REPO', Path(__file__).resolve().parents[1]))
COMPANION = '🔮 850-Companion'
HEAD = '# Kullanıcının düzeltmeleri\n\n## Özet\nSUMMARY_CANARY: kısa yaz, kaynak göster.\n\n## Kurallar\n'


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


engine = load('beyin_v3_share_engine', 'template/.claude/scripts/beyin_v3.py')
companion = load('beyin_v3_share_companion', 'template/.claude/scripts/beyin_v3_companion.py')


def rules_file(size, exact=False):
    """Numbered one-line rules under a summary; exact pads the last rule to size characters."""
    text, count = HEAD, 0
    while len(text) < size:
        count += 1
        text += f'- R{count:04d} kural metni burada durur, kısa ve tek satır.\n'
    if exact:
        text = text[:size - 1] + '\n' if len(text) > size else text
    return text


def section(context, name):
    start = context.index(f'[{COMPANION}/{name}]\n') + len(f'[{COMPANION}/{name}]\n')
    end = context.find(f'\n[{COMPANION}/', start)
    return context[start:end if end >= 0 else len(context)]


class RulesShareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='rules-share-')
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.vault = root / 'vault'
        (self.vault / COMPANION).mkdir(parents=True)
        self.store = engine.MemoryStore(root / 'runtime', self.vault)
        self.bodies = {
            'Core.md': '# Kimlik\nIDENTITY_CANARY\n',
            'Last-Session.md': '# Son oturum\n' + 'Devir kartı satırı.\n' * 120,
            'Threads.md': '# Threads\n## Active Threads\n' + 'Aktif konu satırı.\n' * 200,
            'Journal.md': '# Journal\n## 2026-10-16\nJOURNAL_CANARY\n',
            'Tetikleyici.md': '# Tetikleyici\n- Gradle: `./gradlew --stop`\n',
        }

    def write(self, name, body):
        source = f'{COMPANION}/{name}'
        (self.vault / source).write_text(body, encoding='utf-8', newline='\n')
        with self.store._connect() as db:
            db.execute('DELETE FROM records WHERE id=?', (name,))
        self.store.ingest({'id': name, 'kind': 'note', 'status': 'active', 'text': body,
                           'source': source, 'updated_at': '2026-10-16T10:00:00Z'})

    def write_all(self, rules):
        for name, body in dict(self.bodies, **{'Kurallar.md': rules}).items():
            self.write(name, body)

    def opening(self, budget=5000, warning=''):
        """The opening the hook renders at SessionStart: claim_check always refreshes on a
        new session, so no deferred-check warning rides along here."""
        return companion.context(self.store, budget, '0' * 24, 'claude', warning=warning)

    def test_the_promised_size_is_the_size_that_arrives_whole(self):
        # The number doctor reports has to be a size that arrives whole in the opening.
        # It holds only because the doctor counts the same overhead the hook pays: with the
        # warning counted on one side and not the other, the promise was 3264 against 3108.
        self.write_all(rules_file(45600))
        share = companion.rules_opening(self.store, 5000)['share']
        self.assertGreater(share, 0)
        whole = rules_file(share, exact=True)
        self.assertEqual(len(whole), share)
        self.write_all(whole)
        self.assertFalse(companion.rules_opening(self.store, 5000)['clipped'])
        shown = section(self.opening(), 'Kurallar.md')
        self.assertEqual(shown, whole, 'doctor promised a size the opening does not show whole')

    def test_the_openings_overhead_is_what_the_number_was_measured_with(self):
        # A warning in the opening would move the number without moving the promise, so the
        # report and the opening have to be measured the same way. SessionStart pays no
        # deferred-check warning (claim_check always refreshes), so both sides render bare.
        self.write_all(rules_file(45600))
        with_warning = companion.rules_opening(self.store, 5000)
        bare = companion.context(self.store, 5000, '0' * 24, 'claude')
        self.assertGreater(len(bare), 0)
        self.assertGreaterEqual(with_warning['share'], 0)
        # A 156-character opening warning would cost the rules exactly its length here; the
        # report is only allowed to promise what this opening delivers.
        share = companion.rules_opening(self.store, 5000)['share']
        whole = rules_file(share, exact=True)
        self.write_all(whole)
        self.assertEqual(section(self.opening(), 'Kurallar.md'), whole)

    def test_one_character_more_than_the_promise_is_clipped(self):
        self.write_all(rules_file(45600))
        share = companion.rules_opening(self.store, 5000)['share']
        self.write_all(rules_file(share + 1, exact=True))
        self.assertTrue(companion.rules_opening(self.store, 5000)['clipped'])


if __name__ == '__main__':
    unittest.main()
