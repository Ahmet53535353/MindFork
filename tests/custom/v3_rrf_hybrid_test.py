#!/usr/bin/env python3
"""Tests for Reciprocal Rank Fusion (RRF) and pluggable semantic search in beyin_v3."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('v3_runtime_evaluator', ROOT / 'scripts/evaluate_v3.py')
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)


class RrfHybridSearchTest(unittest.TestCase):
    def setUp(self):
        self.module = evaluator.load_runtime()
        self.assertIsNotNone(self.module, 'Runtime not implemented')
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-rrf-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.state = self.root / 'runtime'
        self.store = self.module.MemoryStore(self.state, self.vault)
        self.addCleanup(lambda: evaluator.close_store(self.store))

    def make_record(self, id, text, memory_type='semantic', project='mindfork', **extra):
        record = {
            'id': id,
            'project': project,
            'kind': 'note',
            'status': 'active',
            'visibility': 'internal',
            'text': text,
            'facts': extra.get('facts', {}),
            'source': f'notes/{id}.md',
            'updated_at': '2026-09-25T01:00:00Z',
            'type': memory_type,
        }
        record.update(extra)
        source = self.vault / record['source']
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(record['text'], encoding='utf-8')
        return record

    def test_rrf_fuse_pure_lexical(self):
        self.assertTrue(hasattr(self.module, '_rrf_fuse'), '_rrf_fuse function should exist')
        lexical = ['docA', 'docB', 'docC']
        semantic = []
        fused = self.module._rrf_fuse(lexical, semantic, k=60)
        self.assertEqual(fused, ['docA', 'docB', 'docC'])

    def test_rrf_fusion_mathematical_boost(self):
        # doc_both ranks #2 in lexical and #1 in semantic -> should beat doc_lex1 (#1 in lexical only)
        lexical = ['doc_lex1', 'doc_both', 'doc_lex2']
        semantic = ['doc_both', 'doc_sem1', 'doc_sem2']
        fused = self.module._rrf_fuse(lexical, semantic, k=60)
        self.assertEqual(fused[0], 'doc_both')
        self.assertEqual(fused[1], 'doc_lex1')

    def test_retrieve_with_semantic_searcher_hook(self):
        # Ingest note-lex: matches keywords
        self.store.ingest(self.make_record('note-lex', 'Payment transaction logging detail'))
        # Ingest note-concept: conceptual match that semantic searcher will favor
        self.store.ingest(self.make_record('note-concept', 'Stripe payment retry gateway architecture'))

        # Without semantic searcher
        res_default = self.store.retrieve('Payment transaction', project='mindfork')
        self.assertEqual(res_default['records'][0]['id'], 'note-lex')

        # With mock semantic searcher that prefers note-concept
        def mock_semantic_ranker(query, eligible_records):
            # Orders note-concept first, note-lex second
            return ['note-concept', 'note-lex']

        self.store.semantic_searcher = mock_semantic_ranker
        res_hybrid = self.store.retrieve('Payment transaction', project='mindfork')
        # note-concept should be elevated
        fused_ids = [r['id'] for r in res_hybrid['records']]
        self.assertIn('note-concept', fused_ids)


if __name__ == '__main__':
    unittest.main()
