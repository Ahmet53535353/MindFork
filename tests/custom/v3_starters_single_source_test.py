#!/usr/bin/env python3
"""Dağıtılan companion varsayılanlarının tip iddiasını denetleyen testler.

2026-10-16'da `type` sınıflandırması düzeltilirken şu bulundu:
`memory-types.md` tanımının **iki** kopyası vardı ve ikisi de aynı yanlış iddiayı
taşıyordu — "`knowledge/concepts/*.md` semantic'tir". Ölçüldüğü için yanlıştı:
concept klasörünün büyük çoğunluğu `procedural`, dolayısıyla "neden / kavram /
fark" sorguları çıkarılan semantic gate'i ile yanlış yere daralıyordu.

Kopyalar:
  * `STARTERS['memory-types.md']` — dağıtılan tek kaynak (yeni vault'a yazılır).
  * `template/850-Companion/memory-types.md` — "v2 seed"; `v3_companion_rules_test`
    onu fixture olarak okuyor, silinemez ama de bakımı sürdürülür.

Ayrışmayı yeniden engellemek için ikisi de aynı yanlış iddiayı taşıyamaz.
"""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPANION_SOURCE = ROOT / 'template/.claude/scripts/beyin_v3_companion.py'
TEMPLATE_SEED = ROOT / 'template/🔮 850-Companion/memory-types.md'


def _starters():
    tree = ast.parse(COMPANION_SOURCE.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'STARTERS':
            return ast.literal_eval(node.value)
    raise AssertionError('STARTERS not found in beyin_v3_companion.py')


def _semantic_section(text):
    assert '### semantic' in text, 'semantic bolumu yok'
    return text.split('### semantic', 1)[-1].split('### ', 1)[0]


class StarterMemoryTypesTest(unittest.TestCase):
    def setUp(self):
        self.starters = _starters()
        self.assertIn('memory-types.md', self.starters)
        self.assertIsInstance(self.starters['memory-types.md'], str)
        self.text = self.starters['memory-types.md']

    def test_starter_does_not_file_concept_notes_under_semantic(self):
        # Method notes are procedural. Filing them under semantic was measurably wrong:
        # a "neden/kavram/fark" query then gated away the notes that answer it.
        self.assertNotIn('knowledge/concepts', _semantic_section(self.text),
                         'starter still claims knowledge/concepts notes are semantic')

    def test_starter_files_concept_notes_under_procedural(self):
        self.assertIn('knowledge/concepts', self.text.split('### procedural', 1)[-1],
                      'the procedural examples must carry what semantic dropped')

    def test_starter_documents_that_type_filters_retrieval(self):
        # `type` is enforced by record_matches_types, not decoration. A starter that
        # omits this is how an untyped file silently disappears from "nasıl ..." queries.
        self.assertIn('filtre', self.text.lower())

    def test_starter_states_untyped_records_are_never_excluded(self):
        # record_matches_types lets type is None through an inferred gate. The starter
        # must not teach the opposite.
        self.assertIn('asla elmez', self.text)

    def test_starter_carries_no_vault_specific_counts(self):
        # Measured numbers belong to the vault that measured them; a starter is written
        # into a fresh vault where those numbers are false.
        for measured in ('56 procedural', 'concept klasörünün 56', '107'):
            self.assertNotIn(measured, self.text)


class V2SeedMatchesStarterTest(unittest.TestCase):
    """The v2 seed is a fixture, not frozen history: v3_companion_rules_test already
    edits its Kurallar.md to drop a stale promise. So its type claim is maintained too."""

    def setUp(self):
        self.seed = TEMPLATE_SEED.read_text(encoding='utf-8')

    def test_seed_does_not_file_concept_notes_under_semantic(self):
        self.assertNotIn('knowledge/concepts', _semantic_section(self.seed),
                         'v2 seed still claims knowledge/concepts notes are semantic')

    def test_seed_states_untyped_records_are_never_excluded(self):
        self.assertIn('asla elmez', self.seed)

    def test_seed_and_starter_agree_on_the_procedural_example(self):
        starter = _starters()['memory-types.md']
        self.assertIn('knowledge/concepts',
                      starter.split('### procedural', 1)[-1].split('### ', 1)[0])
        self.assertIn('knowledge/concepts',
                      self.seed.split('### procedural', 1)[-1].split('## ', 1)[0])


class DistributionTest(unittest.TestCase):
    def test_release_packages_no_companion_template(self):
        # STARTERS is the only distributed companion default: new installs would get
        # two writers racing (STARTERS uses open("x") and never overwrites).
        source = (ROOT / 'scripts/build_v3_release.py').read_text(encoding='utf-8')
        build = source.split('def build(', 1)[-1]
        self.assertNotIn('850-Companion', build,
                         'packaging the template would create a second writer')


if __name__ == '__main__':
    unittest.main()
