"""`beyin.py` finds its command past the flags: the four early-dispatch verbs are real commands.

`beyin.py` reads `argv[0]` as the command, but a vault-local caller may legitimately write
`--vault .` first (a vault note documents exactly that form for `ingest-server`). The runtime
CLI registers 26 verbs through argparse and is reached through a fallthrough, so the flag only
broke the four verbs that short-circuit before it: `yakala`, `update`, `rollback`, `recover`.
Same command, same vault, different argument order, "invalid choice" -- an error message that
says the command does not exist when it does.

These cases run the installed entry point, not a helper, because the defect lives in the
argument walk itself.
"""
from pathlib import Path
import json
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / 'scripts/beyin_entry.py'


class CommandBeforeFlagsTest(unittest.TestCase):
    """`beyin.py <global flags> <verb>` must reach the verb."""

    def entry_argv(self, *args):
        return [str(arg) for arg in args]

    def run_entry(self, vault, *args, timeout=120):
        """Invoke the entry with an argv that a user could actually type."""
        result = subprocess.run([sys.executable, str(vault / 'beyin.py'), *self.entry_argv(*args)],
                                capture_output=True, text=True, encoding='utf-8', cwd=vault, timeout=timeout)
        return result

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.vault = root / 'vault'
        self.state = root / 'state'
        self.vault.mkdir()
        self.state.mkdir()
        installed = subprocess.run([sys.executable, str(ROOT / 'scripts/install_v3.py'), '--vault', str(self.vault),
                                    '--state', str(self.state)], capture_output=True, text=True, encoding='utf-8',
                                   timeout=300)
        self.assertEqual(installed.returncode, 0, installed.stderr)

    def test_early_dispatch_verbs_survive_a_leading_vault_flag(self):
        """`--vault` first is a documented form; the verb must still be found."""
        cases = [
            (['yakala', 'durum'], 'yakala'),
            (['update', '--check'], 'update'),
        ]
        for tail, verb in cases:
            with self.subTest(verb=verb):
                plain = self.run_entry(self.vault, *tail)
                flagged = self.run_entry(self.vault, '--vault', str(self.vault), *tail)
                self.assertNotIn('invalid choice', flagged.stderr,
                                 f'--vault before {verb} reported the verb as unknown')
                self.assertEqual(plain.returncode, flagged.returncode,
                                 f'--vault changed the outcome of {verb}: {flagged.stderr[:300]}')

    def test_a_leading_vault_flag_does_not_change_which_vault_runs(self):
        """`beyin.py` is vault-local; naming this vault must be redundant, never a redirect."""
        same = self.run_entry(self.vault, '--vault', str(self.vault), '--json', 'doctor')
        other = self.run_entry(self.vault, '--vault', str(Path(self.tmp.name) / 'not-a-vault'),
                               '--json', 'doctor')
        self.assertEqual(same.returncode, 0, same.stderr)
        self.assertNotEqual(other.returncode, 0, 'another vault must be refused, not used')
        self.assertIn('vault', other.stderr.lower())

    def test_the_flag_value_is_never_mistaken_for_the_command(self):
        """`--vault .` puts a bare path in argv[1]; treating it as the verb would be a new bug."""
        result = self.run_entry(self.vault, '--vault', str(self.vault), '--json', 'doctor')
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertNotIn('error', payload)


if __name__ == '__main__':
    unittest.main()