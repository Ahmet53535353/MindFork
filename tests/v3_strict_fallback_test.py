"""Strict fallback honors configured exclusions; explicit history stays available."""
import builtins
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import shutil
import subprocess
import tempfile
import unicodedata
import unittest
from typing import Literal
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'template/.claude/scripts'
sys.path.insert(0, str(SCRIPTS))
import beyin_v3 as runtime  # pyright: ignore[reportMissingImports]
import beyin_v3_passage as passage  # pyright: ignore[reportMissingImports]

QUERY = 'quartz observatory calibration'
TEXT = 'Quartz observatory calibration uses a zircon reference.'
ARCHIVE = '📦 900-Archive/'


@contextmanager
def passage_unavailable():
    original = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == 'beyin_v3_passage':
            raise ModuleNotFoundError("simulated unavailable passage module", name=name)
        return original(name, *args, **kwargs)

    with patch('builtins.__import__', side_effect=unavailable):
        yield


class StrictFallbackExclusionsTest(unittest.TestCase):
    def setUp(self):
        self.assertEqual(Path(runtime.__file__ or "").resolve(), SCRIPTS / 'beyin_v3.py')
        self.tmp = tempfile.TemporaryDirectory(prefix='fallback-regression-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.store = runtime.MemoryStore(self.root / 'state', self.vault)
        self.addCleanup(self.store.close)
        self.ingest('live', 'knowledge/live.md')

    def ingest(self, identifier, source):
        target = self.vault / source
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(TEXT, encoding='utf-8')
        return self.store.ingest({'id': identifier, 'source': source, 'text': TEXT,
                                 'facts': {}, 'kind': 'note', 'status': 'active',
                                 'visibility': 'internal', 'updated_at': '2026-09-20T10:00:00Z'})

    def configure(self, prefixes):
        (self.store.state_dir / 'retrieval.json').write_text(
            json.dumps({'strict_exclude': prefixes, 'strict_floor': 0.47}), encoding='utf-8')

    @staticmethod
    def sources(context):
        return {record['source'] for record in context['records']}

    def strict(self):
        return self.store.retrieve(QUERY, strict=True, limit=20)

    def fallback(self):
        with patch.object(passage, 'context_for', side_effect=RuntimeError('forced passage failure')) as failed:
            context = self.store.context_for('hermes', QUERY, strict=True, limit=20)
            failed.assert_called_once()
        return context

    def test_strict_candidates_keep_allowed_records_only(self):
        self.configure([ARCHIVE])
        self.ingest('archive', ARCHIVE + 'snapshot.md')
        candidates = self.store._retrieve(QUERY, strict=True, candidate_only=True)
        self.assertEqual({record['source'] for record in candidates}, {'knowledge/live.md'})

    def test_non_strict_forced_fallback_keeps_explicit_history_available(self):
        self.configure([ARCHIVE])
        source = ARCHIVE + 'snapshot.md'
        self.ingest('archive', source)
        with patch.object(passage, 'context_for', side_effect=RuntimeError('forced passage failure')):
            context = self.store.context_for('hermes', QUERY, strict=False, limit=20)
        self.assertEqual(self.sources(context), {source, 'knowledge/live.md'})

    def test_unavailable_policy_preserves_stale_count_and_custom_pack_metadata(self):
        stale = self.ingest('stale', 'knowledge/stale.md')
        (self.vault / stale['source']).write_text('changed source', encoding='utf-8')
        with passage_unavailable():
            context = self.store.retrieve(QUERY, strict=True, limit=3, budget_chars=321)
        self.assertEqual(context, runtime.pack_context([], 3, 321, stale_count=1))

    def cold_retrieval(self, scripts, imports):
        code = '''
import importlib.util
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
for name in json.loads(sys.argv[4]):
    __import__(name)
import beyin_v3 as runtime
missing = importlib.util.find_spec('beyin_v3_passage') is None
store = runtime.MemoryStore(Path(sys.argv[2]), Path(sys.argv[3]))
try:
    strict = store.retrieve(sys.argv[5], strict=True, limit=20)
    historical = store.retrieve(sys.argv[5], strict=False, limit=20)
    context = store.context_for('hermes', sys.argv[5], strict=True, limit=20)
finally:
    store.close()
print(json.dumps({'missing': missing,
                 'strict': [r['source'] for r in strict['records']],
                 'historical': [r['source'] for r in historical['records']],
                 'context': [r['source'] for r in context['records']]}))
'''
        result = subprocess.run(
            [sys.executable, '-B', '-c', code, str(scripts), str(self.store.state_dir),
             str(self.vault), json.dumps(imports), QUERY], cwd=self.root,
            capture_output=True, text=True, timeout=30, check=True)
        return json.loads(result.stdout)

    def test_cold_interpreter_supports_both_module_import_orders(self):
        self.configure([ARCHIVE])
        self.ingest('archive', ARCHIVE + 'snapshot.md')
        for imports in [['beyin_v3', 'beyin_v3_passage'], ['beyin_v3_passage', 'beyin_v3']]:
            with self.subTest(imports=imports):
                result = self.cold_retrieval(SCRIPTS, imports)
                self.assertFalse(result['missing'])
                self.assertEqual(result['strict'], ['knowledge/live.md'])
                self.assertEqual(result['context'], ['knowledge/live.md'])
                self.assertEqual(set(result['historical']),
                                 {'knowledge/live.md', ARCHIVE + 'snapshot.md'})

    def test_cold_interpreter_with_physically_absent_passage_module(self):
        self.configure([ARCHIVE])
        self.ingest('archive', ARCHIVE + 'snapshot.md')
        scripts = self.root / 'scripts-without-passage'
        scripts.mkdir()
        for source in SCRIPTS.glob('*.py'):
            if source.name != 'beyin_v3_passage.py':
                shutil.copyfile(source, scripts / source.name)
        result = self.cold_retrieval(scripts, ['beyin_v3'])
        self.assertTrue(result['missing'])
        self.assertEqual(result['strict'], [])
        self.assertEqual(result['context'], [])
        self.assertEqual(set(result['historical']),
                         {'knowledge/live.md', ARCHIVE + 'snapshot.md'})

    def test_direct_strict_excludes_runtime_archive_prefix(self):
        self.configure([ARCHIVE])
        self.ingest('archive', ARCHIVE + 'snapshot.md')
        self.assertEqual(self.sources(self.strict()), {'knowledge/live.md'})

    def test_forced_passage_error_excludes_runtime_archive_prefix(self):
        self.configure([ARCHIVE])
        self.ingest('archive', ARCHIVE + 'snapshot.md')
        self.assertEqual(self.sources(self.fallback()), {'knowledge/live.md'})

    def test_explicit_history_search_remains_available(self):
        self.configure([ARCHIVE])
        historical = ARCHIVE + 'snapshot.md'
        self.ingest('archive', historical)
        self.assertEqual(self.sources(self.store.retrieve(QUERY, strict=False)),
                         {historical, 'knowledge/live.md'})
        self.assertIn(historical, self.sources(self.store.context_for('hermes', QUERY, strict=False)))

    def test_unicode_case_and_separator_normalization_matches_passage_pool(self):
        canonical = '📦 900-Arşiv/'
        forms: list[tuple[Literal['NFC', 'NFD'], Literal['NFC', 'NFD']]] = [('NFC', 'NFD'), ('NFD', 'NFC')]
        for source_form, config_form in forms:
            with self.subTest(source_form=source_form, config_form=config_form):
                source = unicodedata.normalize(source_form, canonical) + source_form + '.md'
                self.ingest(source_form, source)
                prefix = unicodedata.normalize(config_form, canonical).upper().replace('/', '\\')
                self.configure([prefix])
                records, _ = self.store._eligible()
                expected = {record['source'] for record in passage.pool(
                    self.store, records, exclude=passage.settings(self.store.state_dir)['exclude'])}
                self.assertEqual(expected, {'knowledge/live.md'})
                self.assertEqual(self.sources(self.strict()), expected)
                self.assertEqual(self.sources(self.fallback()), expected)

    def test_defaults_exclude_daily_and_receipts_without_runtime_config(self):
        for identifier, source in [('daily', 'daily/log.md'), ('receipt', 'receipts/record.md'),
                                   ('case-daily', 'Daily/log.md'), ('case-receipt', 'Receipts/record.md')]:
            self.ingest(identifier, source)
        self.assertEqual(self.sources(self.strict()), {'knowledge/live.md'})
        self.assertEqual(self.sources(self.fallback()), {'knowledge/live.md'})

    def test_custom_config_cannot_remove_default_exclusions_or_change_floor(self):
        self.configure([ARCHIVE])
        for identifier, source in [('daily', 'daily/log.md'), ('receipt', 'receipts/record.md'),
                                   ('archive', ARCHIVE + 'snapshot.md')]:
            self.ingest(identifier, source)
        self.assertEqual(self.sources(self.strict()), {'knowledge/live.md'})
        self.assertEqual(self.sources(self.fallback()), {'knowledge/live.md'})
        self.assertEqual(passage.settings(self.store.state_dir)['floor'], 0.47)

    def test_invalid_runtime_config_uses_defaults(self):
        self.ingest('receipt', 'receipts/record.md')
        for config in ['{invalid', '{"strict_exclude": [null]}', '[]']:
            with self.subTest(config=config):
                (self.store.state_dir / 'retrieval.json').write_text(config, encoding='utf-8')
                self.assertEqual(self.sources(self.strict()), {'knowledge/live.md'})
                self.assertEqual(self.sources(self.fallback()), {'knowledge/live.md'})

    def test_fallback_preserves_context_pack_metadata(self):
        self.configure([ARCHIVE])
        self.ingest('archive', ARCHIVE + 'snapshot.md')
        stale = self.ingest('stale', 'knowledge/stale.md')
        (self.vault / stale['source']).write_text('changed source', encoding='utf-8')
        expected = runtime.pack_context([record for record in self.store._records() if record['id'] == 'live'],
                                        20, 8000, stale_count=1)
        self.assertEqual(self.fallback(), expected)
        self.assertIsInstance(self.fallback(), runtime.PackedContext)

    def test_unavailable_passage_module_fails_closed_for_direct_strict(self):
        self.configure([ARCHIVE])
        self.ingest('archive', ARCHIVE + 'snapshot.md')
        self.ingest('receipt', 'receipts/record.md')
        with passage_unavailable():
            self.assertEqual(self.strict(), runtime.pack_context([], 20, 8000))
            self.assertEqual(self.store._retrieve(QUERY, strict=True, candidate_only=True), [])

    def test_unavailable_passage_module_fails_closed_for_context_for(self):
        self.configure([ARCHIVE])
        self.ingest('archive', ARCHIVE + 'snapshot.md')
        with passage_unavailable():
            result = self.store.context_for('hermes', QUERY, strict=True, limit=20)
        self.assertEqual(result, runtime.pack_context([], 20, 8000))

    def test_unavailable_passage_module_does_not_disable_explicit_history(self):
        self.configure([ARCHIVE])
        source = ARCHIVE + 'snapshot.md'
        self.ingest('archive', source)
        with passage_unavailable():
            self.assertEqual(self.sources(self.store.retrieve(QUERY, strict=False)),
                             {source, 'knowledge/live.md'})


if __name__ == '__main__':
    unittest.main()
