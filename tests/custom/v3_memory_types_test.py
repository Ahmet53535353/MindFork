#!/usr/bin/env python3
"""Tests for type-based memory retrieval and validation in beyin_v3."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('v3_runtime_evaluator', ROOT / 'scripts/evaluate_v3.py')
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)


class MemoryTypesRetrievalTest(unittest.TestCase):
    def setUp(self):
        self.module = evaluator.load_runtime()
        self.assertIsNotNone(self.module, 'Runtime not implemented')
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-memory-types-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.state = self.root / 'runtime'
        self.store = self.module.MemoryStore(self.state, self.vault)
        self.addCleanup(lambda: evaluator.close_store(self.store))

    def make_record(self, id, memory_type=None, text='Shared test content memory'):
        record = {
            'id': id,
            'project': 'mindfork',
            'kind': 'note',
            'visibility': 'internal',
            'text': text,
            'facts': {},
            'source': f'notes/{id}.md',
            'updated_at': '2026-09-25T01:00:00Z',
        }
        if memory_type is not None:
            record['type'] = memory_type
        source = self.vault / record['source']
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(record['text'], encoding='utf-8')
        return record

    def test_validate_memory_types(self):
        # Valid types pass
        for valid_type in ('semantic', 'procedural', 'episodic'):
            rec = self.make_record(f'rec-{valid_type}', memory_type=valid_type)
            validated = self.store._validate(rec)
            self.assertEqual(validated.get('type'), valid_type)

        # Legacy record without type passes
        legacy = self.make_record('rec-legacy')
        validated_legacy = self.store._validate(legacy)
        self.assertNotIn('type', validated_legacy)

        # Invalid type fails
        bad_rec = self.make_record('rec-bad', memory_type='invalid_type')
        with self.assertRaises(ValueError):
            self.store._validate(bad_rec)

        bad_type_val = self.make_record('rec-bad-num', memory_type=123)
        with self.assertRaises(ValueError):
            self.store._validate(bad_type_val)

    def test_retrieve_without_type_filter_returns_all(self):
        self.store.ingest(self.make_record('sem-1', 'semantic', 'Knowledge architecture overview'))
        self.store.ingest(self.make_record('proc-1', 'procedural', 'Workflow architecture guidelines'))
        self.store.ingest(self.make_record('epi-1', 'episodic', 'Session architecture discussion'))

        res = self.store.retrieve('architecture', project='mindfork')
        ids = {r['id'] for r in res['records']}
        self.assertEqual(ids, {'sem-1', 'proc-1', 'epi-1'})

    def test_retrieve_single_type_filter(self):
        self.store.ingest(self.make_record('sem-1', 'semantic', 'Knowledge architecture overview'))
        self.store.ingest(self.make_record('proc-1', 'procedural', 'Workflow architecture guidelines'))
        self.store.ingest(self.make_record('epi-1', 'episodic', 'Session architecture discussion'))

        # Only procedural
        res_proc = self.store.retrieve('architecture', project='mindfork', types='procedural')
        self.assertEqual([r['id'] for r in res_proc['records']], ['proc-1'])

        # Only semantic
        res_sem = self.store.retrieve('architecture', project='mindfork', types='semantic')
        self.assertEqual([r['id'] for r in res_sem['records']], ['sem-1'])

        # Only episodic
        res_epi = self.store.retrieve('architecture', project='mindfork', types='episodic')
        self.assertEqual([r['id'] for r in res_epi['records']], ['epi-1'])

    def test_retrieve_multi_type_filter(self):
        self.store.ingest(self.make_record('sem-1', 'semantic', 'Knowledge architecture overview'))
        self.store.ingest(self.make_record('proc-1', 'procedural', 'Workflow architecture guidelines'))
        self.store.ingest(self.make_record('epi-1', 'episodic', 'Session architecture discussion'))

        res = self.store.retrieve('architecture', project='mindfork', types=['semantic', 'procedural'])
        ids = {r['id'] for r in res['records']}
        self.assertEqual(ids, {'sem-1', 'proc-1'})

    def test_retrieve_invalid_type_raises(self):
        self.store.ingest(self.make_record('sem-1', 'semantic', 'Knowledge architecture overview'))

        with self.assertRaises(ValueError):
            self.store.retrieve('architecture', project='mindfork', types='invalid_type')

        with self.assertRaises(ValueError):
            self.store.retrieve('architecture', project='mindfork', types=['semantic', 'bad_type'])


if __name__ == '__main__':
    unittest.main()
