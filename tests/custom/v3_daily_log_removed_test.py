#!/usr/bin/env python3
"""The daily log is gone: no module, no preference, no file the engine writes.

Ahmet removed the feature on 2026-10-14: the human daily log under `daily/log/` never
carried anything he used, and the switch had been the only thing keeping it dormant.
Deleting the code is the only way to stop it being re-enabled by a stray preference file
or by a future update that restores the module.

This is a removal test, so it is inverted by nature: it asserts an *absence*. It is still
worth having, because the absence is the contract -- a single surviving import in the hook,
or a single surviving preference symbol, is enough to bring the log back.
"""
import ast
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'template/.claude/scripts'


def imports_of(name):
    """Every module name the given runtime file imports, sessionlog included."""
    tree = ast.parse((SCRIPTS / name).read_text(encoding='utf-8'))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


class DailyLogRemovedTest(unittest.TestCase):
    def test_the_sessionlog_module_is_no_longer_shipped(self):
        self.assertFalse((SCRIPTS / 'beyin_v3_sessionlog.py').exists(),
                         'beyin_v3_sessionlog.py hâlâ duruyor; günlük log kodla geri gelir')

    def test_no_runtime_module_imports_it(self):
        for name in ('beyin_v3_hook.py', 'beyin_v3_preferences.py', 'beyin_v3_sync.py',
                     'beyin_v3_projection.py' if (SCRIPTS / 'beyin_v3_projection.py').exists()
                     else 'beyin_v3_projections.py'):
            with self.subTest(module=name):
                self.assertNotIn('beyin_v3_sessionlog', imports_of(name),
                                 f'{name} hâlâ sessionlog import ediyor')

    def test_the_daily_log_preference_symbols_are_gone(self):
        """A surviving `read_daily_log` would let a stale `daily-log.json` switch the log back on."""
        tree = ast.parse((SCRIPTS / 'beyin_v3_preferences.py').read_text(encoding='utf-8'))
        defined = set()
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                defined.add(node.name)
            elif isinstance(node, ast.Assign):
                defined.update(t.id for t in node.targets if isinstance(t, ast.Name))
        self.assertEqual(sorted(n for n in defined if 'daily_log' in n.lower()), [],
                         'preferences içinde günlük log sembolü kaldı')

    def test_a_session_start_writes_nothing_under_daily_log(self):
        """The end-to-end claim: the engine cannot write `daily/log/` even by accident."""
        with tempfile.TemporaryDirectory(prefix='v3-daily-log-removed-') as tmp:
            root = Path(tmp)
            vault = root / 'vault'
            (vault / '🔮 850-Companion').mkdir(parents=True)
            (vault / '🔮 850-Companion' / 'Core.md').write_text('# Kimlik\nBeyin.\n', encoding='utf-8')
            env = {'BEYIN_V3_NO_SPAWN': '1', 'PYTHONDONTWRITEBYTECODE': '1',
                   'PATH': '/usr/bin:/bin', 'HOME': str(root)}
            import os
            result = subprocess.run(
                [sys.executable, str(SCRIPTS / 'beyin_v3_hook.py'),
                 '--vault', str(vault), '--state', str(root / 'state'), '--harness', 'opencode',
                 '--event', 'SessionStart'],
                capture_output=True, env={**os.environ, **env}, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr[:400])
            self.assertFalse((vault / 'daily' / 'log').exists(),
                             'hook daily/log altında bir şey yazdı; günlük log hâlâ yaşıyor')
            text = result.stdout.decode('utf-8', 'replace')
            self.assertNotIn('Günlük log', text, 'hook çıktısında günlük log bildirimi var')

    def test_the_skill_teaches_no_daily_log_block(self):
        """The instructions are part of the removal: a paragraph that tells the agent to fill
        a `daily/log/` block survives a code removal on its own. It did: the feature went on
        2026-10-15 and the skill kept the paragraph until 2026-10-18."""
        skill = ROOT / 'template/.agents/skills/beyin/SKILL.md'
        text = skill.read_text(encoding='utf-8')
        self.assertNotIn('daily/log/` içindeki', text)
        self.assertNotIn('### Özet` bölümünü', text)
        # The preference was removed with the feature; a line that still teaches the switch
        # sends the user to a command that no longer exists.
        self.assertNotIn('--daily-log', text)
        self.assertNotIn('günlük log açık', text)

    def test_no_daily_log_preference_is_consulted_anywhere(self):
        for name in ('beyin_v3_hook.py', 'beyin_v3_preferences.py'):
            with self.subTest(module=name):
                text = (SCRIPTS / name).read_text(encoding='utf-8')
                self.assertNotIn('read_daily_log', text)
                self.assertNotIn('daily-log.json', text)


if __name__ == '__main__':
    unittest.main()
