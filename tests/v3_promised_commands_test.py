"""Every command the shipped instructions promise exists in the CLI.

The unit tests each exercise one command, so none of them notices a command the docs
teach that was renamed or dropped. The first hands-on sweep of the installed vault
(2026-09-27, docs/specs/2026-09-27-human-use-new-surfaces.md E1) walked every
`beyin.py <verb>` in the files a user actually gets and compared it with `--help`;
all of them existed then, and this test keeps that true.
"""
import importlib.util
import os
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(os.environ.get('BEYIN_TEST_REPO', Path(__file__).resolve().parents[1]))

# The files a user receives: the skill, the agent protocol, and the vault docs.
INSTRUCTIONS = ('template/.agents/skills/beyin/SKILL.md', 'template/AGENTS.md',
                'docs/v3/PREFERENCES.md', 'docs/v3/QUICKSTART.md', 'docs/v3/UPDATE.md',
                'docs/v3/RUNTIME.md', 'docs/v3/GLOBAL-BRIDGE.md', 'docs/v3/COMPANION-PARITY.md')
PROMISE = re.compile(r'beyin\.py(?:\s+--[\w-]+)*\s+([a-z][a-z-]+)')
# The installed `beyin.py` is scripts/beyin_entry.py byte for byte (install_v3.py), and that
# entry intercepts a few commands before the subparser sees them, so the registry is both.
ENTRY_DISPATCH = re.compile(r"(?:args\.)?command == '([a-z-]+)'")
# update/rollback/recover are intercepted before the subparser: a second parser is built for
# them with a positional `choices` tuple, so that tuple is part of the command surface too.
ENTRY_CHOICES = re.compile(r"choices=\(([^)]*)\)")


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class PromisedCommandTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cli = load('beyin_v3_promised_cli', 'scripts/beyin_v3.py')
        cls.verbs = set(cls.cli.parser()._subparsers._group_actions[0].choices)
        entry = (ROOT / 'scripts/beyin_entry.py').read_text(encoding='utf-8')
        intercepted = set(ENTRY_DISPATCH.findall(entry))
        for group in ENTRY_CHOICES.findall(entry):
            intercepted.update(re.findall(r"'([a-z][a-z-]*)'", group))
        cls.entry_only = intercepted - cls.verbs
        cls.known = cls.verbs | cls.entry_only

    def promised(self):
        found = {}
        for relative in INSTRUCTIONS:
            path = ROOT / relative
            if not path.is_file():
                continue
            for match in PROMISE.finditer(path.read_text(encoding='utf-8')):
                found.setdefault(match.group(1), set()).add(Path(relative).name)
        return found

    def test_every_promised_command_is_registered(self):
        promised = self.promised()
        self.assertGreaterEqual(len(promised), 10, 'talimat dosyaları komut sözü vermiyor')
        self.assertIn('update', self.entry_only, 'giriş betiği update yakalamıyor')
        missing = {verb: sorted(where) for verb, where in promised.items() if verb not in self.known}
        self.assertEqual(missing, {}, f'sözü verilen ama kayıtlı olmayan komut: {missing}')

    def test_the_handoff_commands_are_reachable_from_the_instructions(self):
        # The card model is only usable if the agent is told how to archive the file it writes,
        # so both the compaction command and the preferences switch must stay documented.
        promised = self.promised()
        for verb in ('companion-compact', 'preferences', 'recap', 'doctor'):
            with self.subTest(command=verb):
                self.assertIn(verb, promised, f'{verb} talimatlarda anlatılmıyor')
                self.assertIn(verb, self.known)

    def test_the_hygiene_notice_names_the_command_that_fixes_it(self):
        # The notice tells the agent which command to run; that command has to exist, or the
        # advice is a dead end the agent can only report back as broken.
        companion = load('beyin_v3_notice_companion', 'template/.claude/scripts/beyin_v3_companion.py')
        text = (ROOT / 'template/.claude/scripts/beyin_v3_companion.py').read_text(encoding='utf-8')
        named = set(PROMISE.findall(text)) | {'companion-compact'}
        self.assertTrue(named, 'hijyen uyarısı bir komut adı vermiyor')
        for verb in named:
            with self.subTest(command=verb):
                self.assertIn(verb, self.known, f'uyarıda geçen {verb} yok')
        self.assertIn('hygiene', dir(companion))


if __name__ == '__main__':
    unittest.main()
