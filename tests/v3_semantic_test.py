#!/usr/bin/env python3
"""Independent frozen semantic gates; synthetic local records only."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('evaluate_v3', ROOT / 'scripts/evaluate_v3.py')
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)


class SemanticContractTest(unittest.TestCase):
    def test_frozen_fixture_identity_and_split(self):
        fixture, digest = evaluator.read_fixture()
        self.assertEqual(digest, '26755d6fb2ab368f5c7b5882cb2dd33ef651404f366bce45a4632deae57099bc')
        self.assertEqual(len(fixture['records']), 12)
        self.assertEqual(sum(c.get('split') == 'holdout' for c in fixture['cases']), 6)
        self.assertEqual(len(fixture['cases']), 16)

    def test_development_and_holdout_gates(self):
        report = evaluator.evaluate()
        self.assertEqual(report['status'], 'evaluated', 'Runtime missing means not implemented, not passing.')
        for split in ('development', 'holdout'):
            with self.subTest(split=split):
                metrics = report[split]
                self.assertEqual(metrics['recall_at_5'], 1)
                self.assertEqual(metrics['forbidden_count'], 0)
                self.assertEqual(metrics['abstention_accuracy'], 1)
                self.assertEqual(metrics['structured_fact_retention'], 1)
                self.assertEqual(metrics['privacy_canary_leaks'], 0)
                self.assertTrue(metrics['harness_equivalence'])
                self.assertTrue(metrics['passed'])

    def test_evaluator_rejects_broken_harness_adapter(self):
        # Prove equality gate is testing a real harness function, not tautological calls.
        module = evaluator.load_runtime()
        self.assertIsNotNone(module)
        fixture, _ = evaluator.read_fixture()
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory(prefix='v3-adapter-negative-') as tmp:
            store = evaluator.seed_store(module, Path(tmp), fixture)
            try:
                original = module.shared_context
                def broken(store, harness, query, **kwargs):
                    response = original(store, harness, query, **kwargs)
                    if harness == 'codex':
                        response = dict(response, omitted_count=999)
                    return response
                with patch.object(module, 'shared_context', broken):
                    result = evaluator.score_case(module, store, fixture['cases'][0], {r['id']: r for r in fixture['records']})
                self.assertFalse(result['harness_equivalent'])
                self.assertFalse(result['passed'])
            finally:
                evaluator.close_store(store)


if __name__ == '__main__':
    unittest.main()
