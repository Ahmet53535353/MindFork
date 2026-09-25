"""Packaged runtime code imports only the standard library and its own modules.

The installer promises Python 3.11+ and nothing else. An optional backend (for example a local
model server) must stay an external process: its Python packages are never imported here.
"""
import ast
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
# Exactly the Python files the release builder packages (scripts/build_v3_release.py).
PACKAGED = sorted([ROOT / 'scripts' / name for name in ('install_v3.py', 'beyin_v3.py', 'beyin_entry.py')]
                  + list((ROOT / 'template/.claude/scripts').glob('beyin_v3*.py')))


def imported(path):
    """Every absolute import in the file, including lazy imports inside functions."""
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name.split('.')[0]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            yield node.lineno, node.module.split('.')[0]


def allowed(name):
    return name in sys.stdlib_module_names or name.startswith('beyin') or name == '_portalock'


class StdlibImportTest(unittest.TestCase):
    def test_packaged_runtime_has_no_third_party_import(self):
        self.assertGreater(len(PACKAGED), 20)
        offenders = [f'{path.relative_to(ROOT).as_posix()}:{line} {name}'
                     for path in PACKAGED for line, name in imported(path) if not allowed(name)]
        self.assertEqual(offenders, [])

    def test_the_guard_rejects_model_runtimes(self):
        for name in ('torch', 'laya', 'transformers', 'numpy', 'requests'):
            self.assertFalse(allowed(name), name)


if __name__ == '__main__':
    unittest.main()
