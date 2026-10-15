#!/usr/bin/env python3
"""The Minecraft rules are gone: no detector, no two-layer trigger, no starter link.

Ahmet removed them on 2026-10-15: the rules were one project's rules, and a project
rule in the companion folder is a rule every other session reads for nothing. The
general half was kept, not lost -- "empty the memory before you measure" moved to
`Test-Kuralları.md` madde 22, which is what `beyin_kosullu_minecraft_kurallari`
had been pointing at all along.

This is a removal test, so it is inverted by nature: it asserts an *absence*. It is
still worth having, because the absence is the contract. `minecraft_project()` reads
build files on every session to decide whether a Minecraft rule applies; with the rule
gone that is dead work that also invents a project taxonomy nobody maintains. And
`STARTERS` still wrote a link to `Minecraft-Kuralları.md`, a file the installer never
creates, so every new vault started with a dangling reference.
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'template/.claude/scripts'
COMPANION = SCRIPTS / 'beyin_v3_companion.py'

GONE_FUNCTIONS = ('minecraft_project', 'tetikleyici_katman')
GONE_CONSTANTS = ('MINECRAFT_MOD_FILES', 'MINECRAFT_TEXT', 'OLCUM_BASLIGI',
                  'OLCUM_DISI_GEREKCE')


def module_level_names(path):
    """Function and constant names bound at module level, the way the removal was made."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def function_signatures(path):
    """Argument names of every top-level def, so a dead parameter cannot linger."""
    tree = ast.parse(path.read_text(encoding='utf-8'))
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            out[node.name] = [a.arg for a in list(args.posonlyargs) + list(args.args)]
    return out


class MinecraftRulesRemovedTest(unittest.TestCase):
    def test_the_detector_and_the_two_layer_trigger_are_gone(self):
        defined = module_level_names(COMPANION)
        for name in GONE_FUNCTIONS:
            with self.subTest(symbol=name):
                self.assertNotIn(name, defined,
                                 f'{name} hâlâ duruyor; kural yokken proje tespiti boşa çalışır')

    def test_the_minecraft_only_constants_are_gone(self):
        defined = module_level_names(COMPANION)
        for name in GONE_CONSTANTS:
            with self.subTest(symbol=name):
                self.assertNotIn(name, defined, f'{name} artık kullanan bir kural yok')

    def test_no_call_site_survives(self):
        source = COMPANION.read_text(encoding='utf-8')
        for name in GONE_FUNCTIONS:
            with self.subTest(symbol=name):
                self.assertNotIn(f'{name}(', source.replace(f'def {name}(', ''),
                                 f'{name} hâlâ bir yerde çağrılıyor')

    def test_the_starter_writes_no_minecraft_section(self):
        """`STARTERS` seeds every new vault; a link to a file it never creates is dangling."""
        tree = ast.parse(COMPANION.read_text(encoding='utf-8'))
        starters = next(n.value for n in tree.body
                        if isinstance(n, ast.Assign) and any(
                            isinstance(t, ast.Name) and t.id == 'STARTERS' for t in n.targets))
        text = ' '.join(part.value for part in starters.values if isinstance(part, ast.Constant))
        self.assertNotIn('Minecraft', text, 'STARTERS hâlâ Minecraft bölümü yazıyor')
        self.assertNotIn('Oyun içi ölçüm', text, 'STARTERS hâlâ oyun içi ölçüm bölümü yazıyor')

    def test_the_cwd_parameter_is_gone_from_context(self):
        """`cwd` existed only so the Minecraft detector could see the project directory.

        The upcoming upstream merge renames this parameter to `project` and gives it a
        real use (project-scoped rules); keeping a dead `cwd` here would collide with it.
        """
        signatures = function_signatures(COMPANION)
        self.assertIn('context', signatures, 'context() kayboldu')
        self.assertNotIn('cwd', signatures['context'],
                         'context() hâlâ cwd alıyor; Minecraft tespiti kalktıysa bu da ölü')

    def test_no_shipped_module_mentions_minecraft_rules(self):
        for path in sorted(SCRIPTS.glob('*.py')):
            text = path.read_text(encoding='utf-8')
            with self.subTest(module=path.name):
                self.assertNotIn('Minecraft-Kurallar', text,
                                 f'{path.name} silinen kural dosyasına hâlâ bağlantı veriyor')


if __name__ == '__main__':
    unittest.main()