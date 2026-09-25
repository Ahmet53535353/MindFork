#!/usr/bin/env python3
"""Tests for automatic memory-type inference from query intent in beyin_v3."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('v3_runtime_evaluator', ROOT / 'scripts/evaluate_v3.py')
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)


class InferTypesUnitTest(unittest.TestCase):
    def setUp(self):
        self.module = evaluator.load_runtime()
        self.assertIsNotNone(self.module, 'Runtime not implemented')

    def test_episodic_cue_returns_episodic(self):
        self.assertEqual(self.module.infer_types('dün nerede kalmıştık'), ['episodic'])

    def test_procedural_cue_returns_procedural(self):
        self.assertEqual(self.module.infer_types('deploy nasıl yapılır'), ['procedural'])

    def test_semantic_cue_returns_semantic(self):
        self.assertEqual(self.module.infer_types('mimari kararımız neydi'), ['semantic'])

    def test_no_cue_returns_none(self):
        self.assertIsNone(self.module.infer_types('masa'))

    def test_empty_query_returns_none(self):
        self.assertIsNone(self.module.infer_types(''))

    def test_conflicting_cues_return_none(self):
        # episodic (dun, oturum, konusmustuk) plus procedural (adim): doubtful, keep all.
        self.assertIsNone(self.module.infer_types('dün oturumda deploy adımlarını konuşmuştuk'))


class InferTypesIntegrationTest(unittest.TestCase):
    def setUp(self):
        self.module = evaluator.load_runtime()
        self.assertIsNotNone(self.module, 'Runtime not implemented')
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-type-infer-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.store = self.module.MemoryStore(self.root / 'runtime', self.vault)
        self.addCleanup(lambda: evaluator.close_store(self.store))

    def test_untyped_records_survive_inferred_filter(self):
        # Soft gate semantics: a guess never hides notes written before typing existed.
        self.store.ingest(self.make_record('legacy', 'oturumda konuşulan eski kayıt', None))
        self.store.ingest(self.make_record('sem-1', 'oturum planı mimari karar olarak kabul edildi', 'semantic'))

        res = self.store.retrieve('dün oturumda konuştuklarımızı hatırla', project='mindfork')
        ids = [r['id'] for r in res['records']]
        self.assertEqual(ids, ['legacy'])

    def make_record(self, id, text, memory_type, **extra):
        record = {
            'id': id,
            'project': 'mindfork',
            'kind': 'note',
            'status': 'active',
            'visibility': 'internal',
            'text': text,
            'facts': {},
            'source': f'notes/{id}.md',
            'updated_at': '2026-09-25T01:00:00Z',
        }
        if memory_type is not None:
            record['type'] = memory_type
        record.update(extra)
        source = self.vault / record['source']
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(record['text'], encoding='utf-8')
        return record

    def test_retrieve_without_types_filter_infers_episodic(self):
        self.store.ingest(self.make_record('ep-1', 'oturumda konuştuk planı yarına bıraktık', 'episodic'))
        self.store.ingest(self.make_record('sem-1', 'oturum planı mimari karar olarak kabul edildi', 'semantic'))
        self.store.ingest(self.make_record('pro-1', 'oturum planı için kontrol listesi kuralı', 'procedural'))

        res = self.store.retrieve('dün oturumda konuştuklarımızı hatırla', project='mindfork')
        ids = [r['id'] for r in res['records']]
        self.assertEqual(ids, ['ep-1'])

    def test_explicit_types_overrides_inference(self):
        self.store.ingest(self.make_record('ep-1', 'oturumda konuştuk planı yarına bıraktık', 'episodic'))
        self.store.ingest(self.make_record('pro-1', 'oturum planı için kontrol listesi kuralı', 'procedural'))

        # The query reads episodic, but the caller asked explicitly for procedural.
        res = self.store.retrieve('dün oturumda konuştuk', project='mindfork', types='procedural')
        ids = [r['id'] for r in res['records']]
        self.assertEqual(ids, ['pro-1'])

    def test_empty_query_output_is_unchanged(self):
        self.store.ingest(self.make_record('ep-1', 'oturumda konuştuk planı yarına bıraktık', 'episodic'))
        self.store.ingest(self.make_record('sem-1', 'oturum planı mimari karar olarak kabul edildi', 'semantic'))
        inferred = self.store.retrieve('', project='mindfork')
        # Empty query carries no cues: the established empty-scoped-listing
        # behavior must survive inference untouched.
        ids = sorted(r['id'] for r in inferred['records'])
        self.assertEqual(ids, [])


if __name__ == '__main__':
    unittest.main()
