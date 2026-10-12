"""Person notes (`kind: person`): the beyin skill's convention must survive sync and retrieval."""
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))

from beyin_v3_sync import SyncEngine, parse

TEMPLATE = ROOT / 'template/📋 Templates/Kisi.md'
SKILL = ROOT / 'template/.agents/skills/beyin/SKILL.md'


class PersonNotesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.vault = root / 'vault'
        self.vault.mkdir()
        (root / 'state').mkdir()
        self.engine = SyncEngine(self.vault, root / 'state')

    def create(self, source, text, metadata):
        result = self.engine.note_create(source, text, metadata=metadata)
        self.assertEqual(result['status'], 'succeeded')
        return result

    def records(self, query):
        return self.engine.store.retrieve(query)['records']

    def test_person_note_keeps_kind_facts_and_aliases(self):
        self.create('notes/kisiler/ayse-yilmaz.md', '# Ayşe Yılmaz\n\n## Beyan\n- 2026-10-12 (kullanıcı): danışman hocam.',
                    {'kind': 'person', 'title': 'Ayşe Yılmaz', 'aliases': ['Ayşe hoca'],
                     'facts': {'kurum': 'Örnek Üniversitesi', 'rol': 'Doçent'}, 'visibility': 'internal'})
        metadata, _ = parse((self.vault / 'notes/kisiler/ayse-yilmaz.md').read_text(encoding='utf-8'))
        self.assertEqual(metadata['kind'], 'person')
        self.assertEqual(metadata['aliases'], ['Ayşe hoca'])
        self.assertEqual(metadata['facts']['rol'], 'Doçent')
        found = self.records('Ayşe Yılmaz ne iş yapıyor')
        self.assertEqual(found[0]['source'], 'notes/kisiler/ayse-yilmaz.md')
        self.assertEqual(found[0]['kind'], 'person')

    def test_alias_and_facts_reach_the_person_card(self):
        # The body never names the alias or the institution: only metadata can match.
        self.create('notes/kisiler/mehmet-kaya.md', '# Mehmet Kaya\n\n## Temaslar\n- 2026-10-01: kahve.',
                    {'kind': 'person', 'title': 'Mehmet Kaya', 'aliases': ['Memo'],
                     'facts': {'kurum': 'Kuzeyrüzgarı'}})
        self.create('notes/baska.md', 'Proje toplantısı notları.', {'kind': 'note'})
        self.assertEqual(self.records('Memo ile ne konuştuk')[0]['source'], 'notes/kisiler/mehmet-kaya.md')
        self.assertEqual(self.records('Kuzeyrüzgarı')[0]['source'], 'notes/kisiler/mehmet-kaya.md')

    def test_private_person_note_stays_out_of_context(self):
        self.create('notes/kisiler/gizli.md', '# Zeynep Demir', {'kind': 'person', 'title': 'Zeynep Demir', 'visibility': 'private'})
        self.assertEqual(self.records('Zeynep Demir'), [])

    def test_template_parses_and_is_not_a_person_record(self):
        text = TEMPLATE.read_text(encoding='utf-8')
        metadata, body = parse(text)
        self.assertNotIn('kind', metadata)  # an empty template must not show up as a person
        self.assertIn('# kind: person', text)
        self.assertEqual(set(metadata['facts']), {'kurum', 'rol', 'iliski', 'son_temas'})
        for heading in ('## Beyan', '## Çıkarım (onay bekliyor)', '## Temaslar', '## Kaynaklar'):
            self.assertIn(heading, body)

    def test_skill_example_is_valid_note_create_json(self):
        skill = SKILL.read_text(encoding='utf-8')
        section = skill.split('## Kişi notları', 1)[1].split('\n## ', 1)[0]
        example = json.loads(re.search(r'```json\n(.*?)\n```', section, re.S)[1])
        self.assertEqual(example['metadata']['kind'], 'person')
        self.assertTrue(example['source'].startswith('notes/kisiler/'))
        self.create(example['source'], example['text'], example['metadata'])
        self.assertEqual(self.records('Ayşe hoca')[0]['source'], example['source'])


if __name__ == '__main__':
    unittest.main()
