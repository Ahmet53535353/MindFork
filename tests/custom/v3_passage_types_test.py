"""Type gates on the strict passage path: soft inferred gate, explicit filter, cache safety."""
from pathlib import Path
import importlib.util
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'template/.claude/scripts'
sys.path.insert(0, str(SCRIPTS))
import beyin_v3 as runtime  # noqa: E402
import beyin_v3_passage as passage  # noqa: E402

PROC_QUERY = 'zirkon kovası deploy nasıl yapılandırılır'
EPIS_QUERY = 'zirkon kovası deploy dün konuşmuştuk'
NEUTRAL_QUERY = 'zirkon kovası deploy'

PROC_TEXT = '# Kova\n\nZirkon sunucusunda deploy kovası her gece çalışır; kova yolu /srv/zirkon/kova.'
EPIS_TEXT = '# Olay\n\nDün zirkon sunucusunda deploy kovası dolmuştu; kova temizlendi, deploy gecikti.'
OPEN_TEXT = '# Açık\n\nZirkon makinesinde deploy kovası sabah kontrol edilir, kova günlük log taşır.'


class PassageTypeGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-passage-types-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.store = runtime.MemoryStore(self.root / 'runtime', self.vault)
        for i, (memory_type, text) in enumerate((('procedural', PROC_TEXT), ('episodic', EPIS_TEXT), (None, OPEN_TEXT))):
            source = f'notes/kayit-{i}.md'
            (self.vault / source).parent.mkdir(parents=True, exist_ok=True)
            (self.vault / source).write_text(text, encoding='utf-8')
            record = {'id': f'kayit-{i}', 'kind': 'note', 'visibility': 'internal', 'text': text,
                      'facts': {}, 'source': source, 'updated_at': '2026-09-20T10:00:00Z'}
            if memory_type is not None:
                record['type'] = memory_type
            self.store.ingest(record)

    def strict(self, query, **kwargs):
        return passage.context_for(self.store, 'claude', query, strict=True, **kwargs)

    def sources(self, query, **kwargs):
        return [record['source'] for record in self.strict(query, **kwargs)['records']]

    def cache_bytes(self):
        return (self.store.state_dir / passage.CACHE_NAME).read_bytes()

    def test_baseline_neutral_query_returns_every_source(self):
        self.assertEqual(len(self.sources(NEUTRAL_QUERY)), 3)

    def test_inferred_gate_is_soft_on_passage_path(self):
        sources = self.sources(PROC_QUERY)
        self.assertIn('notes/kayit-0.md', sources)  # procedural stays
        self.assertIn('notes/kayit-2.md', sources)  # untyped is never filtered
        self.assertNotIn('notes/kayit-1.md', sources)  # contradicting typed record is excluded
        sources = self.sources(EPIS_QUERY)
        self.assertIn('notes/kayit-1.md', sources)
        self.assertNotIn('notes/kayit-0.md', sources)

    def test_explicit_types_is_strict_on_passage_path(self):
        self.assertEqual(self.sources(NEUTRAL_QUERY, types='episodic'), ['notes/kayit-1.md'])
        self.assertEqual(self.sources(NEUTRAL_QUERY, types=['procedural']), ['notes/kayit-0.md'])

    def test_explicit_types_overrides_inference(self):
        # The query whispers procedural; the caller's explicit episodic filter wins.
        self.assertEqual(self.sources(PROC_QUERY, types='episodic'), ['notes/kayit-1.md'])

    def test_invalid_types_raises_before_any_index(self):
        with self.assertRaises(ValueError):
            self.strict(NEUTRAL_QUERY, types='bogus')
        with self.assertRaises(ValueError):
            self.strict(NEUTRAL_QUERY, types=['episodic', 'bogus'])
        self.assertFalse((self.store.state_dir / passage.CACHE_NAME).exists())

    def test_type_gates_never_touch_the_cache(self):
        self.sources(NEUTRAL_QUERY)
        first = self.cache_bytes()
        self.sources(PROC_QUERY)
        self.sources(NEUTRAL_QUERY, types='episodic')
        self.assertEqual(first, self.cache_bytes())

    def test_store_dispatch_and_fallback_carry_types(self):
        sources = [record['source'] for record in
                   self.store.context_for('claude', NEUTRAL_QUERY, strict=True, types='procedural')['records']]
        self.assertEqual(sources, ['notes/kayit-0.md'])
        sources = [record['source'] for record in
                   self.store.retrieve(NEUTRAL_QUERY, types='procedural')['records']]
        self.assertEqual(sources, ['notes/kayit-0.md'])

    def test_missing_supersedes_key_does_not_break_either_path(self):
        # Payloads normally carry supersedes from validation; a hand-repaired database
        # without the key must degrade to "supersedes nothing", not KeyError.
        import sqlite3
        with sqlite3.connect(self.store.database) as db:
            payload = json.loads(db.execute("SELECT payload FROM records WHERE id='kayit-0'").fetchone()[0])
            payload.pop('supersedes')
            db.execute("UPDATE records SET payload=? WHERE id='kayit-0'", (json.dumps(payload, ensure_ascii=False),))
            db.commit()
        self.assertIn('notes/kayit-0.md', self.sources(NEUTRAL_QUERY))  # passage path
        note_ids = [record['id'] for record in self.store.retrieve(NEUTRAL_QUERY)['records']]
        self.assertIn('kayit-0', note_ids)  # note path


if __name__ == '__main__':
    unittest.main()
