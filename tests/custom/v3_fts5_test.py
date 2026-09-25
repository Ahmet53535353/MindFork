#!/usr/bin/env python3
"""Tests for SQLite FTS5 (BM25) full-text indexing in beyin_v3."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('v3_runtime_evaluator', ROOT / 'scripts/evaluate_v3.py')
evaluator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluator)


class Fts5IndexingTest(unittest.TestCase):
    def setUp(self):
        self.module = evaluator.load_runtime()
        self.assertIsNotNone(self.module, 'Runtime not implemented')
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-fts5-test-')
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

    def test_fts5_virtual_table_created(self):
        with sqlite3.connect(self.store.database) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn('records_fts', tables)

    def test_fts5_synced_on_ingest(self):
        rec = self.make_record('stripe-note', 'StripeWebhookHandler handles payment exceptions ERR_401_EXPIRED')
        self.store.ingest(rec)

        with sqlite3.connect(self.store.database) as db:
            found = db.execute("SELECT id FROM records_fts WHERE records_fts MATCH 'StripeWebhookHandler'").fetchall()
        self.assertEqual(found, [('stripe-note',)])

    def test_fts5_synced_on_update_task(self):
        task = self.make_record('task-sync', 'Initial pending migration task', kind='task')
        self.store.ingest(task)

        # Update text
        new_source = self.vault / task['source']
        new_source.write_text('Updated final deployment step for database', encoding='utf-8')
        self.store.update_task('task-sync', 1, {'text': 'Updated final deployment step for database'})

        with sqlite3.connect(self.store.database) as db:
            old_search = db.execute("SELECT id FROM records_fts WHERE records_fts MATCH 'migration'").fetchall()
            new_search = db.execute("SELECT id FROM records_fts WHERE records_fts MATCH 'deployment'").fetchall()

        self.assertEqual(old_search, [])
        self.assertEqual(new_search, [('task-sync',)])

    def test_fts5_auto_rebuild_from_records(self):
        rec = self.make_record('legacy-1', 'Legacy record that existed before FTS5 index')
        self.store.ingest(rec)

        # Drop the FTS table manually to simulate legacy database
        with sqlite3.connect(self.store.database) as db:
            db.execute("DROP TABLE records_fts")
        evaluator.close_store(self.store)

        # Reopen store
        reopened = self.module.MemoryStore(self.state, self.vault)
        self.addCleanup(lambda: evaluator.close_store(reopened))

        with sqlite3.connect(reopened.database) as db:
            found = db.execute("SELECT id FROM records_fts WHERE records_fts MATCH 'Legacy'").fetchall()
        self.assertEqual(found, [('legacy-1',)])

    def test_fts5_exact_symbol_and_turkish_retrieval(self):
        self.store.ingest(self.make_record('code-sym', 'Fix for StripeWebhookHandler in payment gateway'))
        self.store.ingest(self.make_record('gen-pay', 'General payment architecture notes'))

        res = self.store.retrieve('StripeWebhookHandler', project='mindfork')
        self.assertTrue(len(res['records']) > 0)
        self.assertEqual(res['records'][0]['id'], 'code-sym')


    def test_fts5_rebuild_survives_malformed_payload(self):
        # The lexical index is derived data: a corrupt payload must never break
        # opening the store, and it must not block indexing of healthy records.
        self.store.ingest(self.make_record('ok-1', 'Healthy indexable record'))
        self.store.ingest(self.make_record('bad-1', 'Payload will be corrupted'))
        with sqlite3.connect(self.store.database) as db:
            db.execute("UPDATE records SET payload='{broken' WHERE id='bad-1'")
            db.execute("DELETE FROM records_fts")
        evaluator.close_store(self.store)

        reopened = self.module.MemoryStore(self.state, self.vault)
        self.addCleanup(lambda: evaluator.close_store(reopened))
        with sqlite3.connect(reopened.database) as db:
            found = db.execute("SELECT id FROM records_fts WHERE records_fts MATCH 'Healthy'").fetchall()
        self.assertEqual(found, [('ok-1',)])
        with sqlite3.connect(reopened.database) as db:
            indexed = [row[0] for row in db.execute("SELECT id FROM records_fts")]
        self.assertNotIn('bad-1', indexed)

    def metadata_value(self, store, key):
        with sqlite3.connect(store.database) as db:
            row = db.execute("SELECT value FROM metadata WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def test_rebuild_counts_malformed_rows_in_metadata(self):
        self.store.ingest(self.make_record('ok-1', 'Healthy indexable record'))
        self.store.ingest(self.make_record('ok-2', 'Another healthy record'))
        self.store.ingest(self.make_record('bad-1', 'Payload will be corrupted'))
        with sqlite3.connect(self.store.database) as db:
            db.execute("UPDATE records SET payload='{broken' WHERE id='bad-1'")
            db.execute("DELETE FROM records_fts")
        evaluator.close_store(self.store)

        reopened = self.module.MemoryStore(self.state, self.vault)
        self.addCleanup(lambda: evaluator.close_store(reopened))
        self.assertEqual(self.metadata_value(reopened, 'fts_malformed_skipped'), '1')
        with sqlite3.connect(reopened.database) as db:
            indexed = sorted(row[0] for row in db.execute("SELECT id FROM records_fts"))
        self.assertEqual(indexed, ['ok-1', 'ok-2'])

    def test_clean_rebuild_writes_no_counter(self):
        self.store.ingest(self.make_record('ok-1', 'Healthy indexable record'))
        with sqlite3.connect(self.store.database) as db:
            db.execute("DELETE FROM records_fts")
        evaluator.close_store(self.store)

        reopened = self.module.MemoryStore(self.state, self.vault)
        self.addCleanup(lambda: evaluator.close_store(reopened))
        self.assertIsNone(self.metadata_value(reopened, 'fts_malformed_skipped'))
        with sqlite3.connect(reopened.database) as db:
            self.assertEqual(db.execute("SELECT id FROM records_fts").fetchall(), [('ok-1',)])

    def test_missing_supersedes_key_survives_note_path(self):
        self.store.ingest(self.make_record('ok-1', 'Record without supersedes key'))
        with sqlite3.connect(self.store.database) as db:
            payload = json.loads(db.execute("SELECT payload FROM records WHERE id='ok-1'").fetchone()[0])
            payload.pop('supersedes')
            db.execute("UPDATE records SET payload=? WHERE id='ok-1'", (json.dumps(payload, ensure_ascii=False),))
            db.commit()
        found = self.store.retrieve('Record supersedes', project='mindfork')
        self.assertEqual([record['id'] for record in found['records']], ['ok-1'])

    def test_bm25_rank_overrides_recency_and_missing_rows_queue_last(self):
        # Overlap score is only the admission gate; BM25 rank dominates. The rare-token
        # record wins despite being oldest; when its index row is removed it falls out
        # of the BM25 list entirely and queues after every BM25 hit.
        self.store.ingest(self.make_record('nadir-a', 'webhook imza kontrolu', updated_at='2026-01-01T00:00:00Z'))
        self.store.ingest(self.make_record('sik-b', 'payment fatura listesi', updated_at='2026-06-01T00:00:00Z'))
        self.store.ingest(self.make_record('sik-c', 'payment geri odeme', updated_at='2026-07-01T00:00:00Z'))
        order = [record['id'] for record in self.store.retrieve('payment webhook', project='mindfork')['records']]
        self.assertEqual(order[0], 'nadir-a')
        with sqlite3.connect(self.store.database) as db:
            db.execute("DELETE FROM records_fts WHERE id='nadir-a'")
            db.commit()
        order = [record['id'] for record in self.store.retrieve('payment webhook', project='mindfork')['records']]
        self.assertEqual(order[0], 'sik-c')
        self.assertEqual(order[-1], 'nadir-a')

    def test_strict_path_skips_fts_and_query_errors_are_counted(self):
        self.store.ingest(self.make_record('ok-1', 'Healthy indexable record'))
        with sqlite3.connect(self.store.database) as db:
            db.execute("DROP TABLE records_fts")
            db.commit()
        strict = self.store.retrieve('Healthy record', project='mindfork', strict=True)
        self.assertEqual([record['id'] for record in strict['records']], ['ok-1'])
        self.assertIsNone(self.metadata_value(self.store, 'fts_query_errors'))  # strict never queries FTS
        relaxed = self.store.retrieve('Healthy record', project='mindfork')
        self.assertEqual([record['id'] for record in relaxed['records']], ['ok-1'])  # degrade, never break
        self.assertEqual(self.metadata_value(self.store, 'fts_query_errors'), '1')

    def test_read_only_store_degrades_without_writing_counters(self):
        self.store.ingest(self.make_record('ok-1', 'Healthy indexable record'))
        with sqlite3.connect(self.store.database) as db:
            db.execute("DROP TABLE records_fts")
            db.commit()
        evaluator.close_store(self.store)
        reader = self.module.MemoryStore(self.state, self.vault, read_only=True)
        self.addCleanup(lambda: evaluator.close_store(reader))
        found = reader.retrieve('Healthy record', project='mindfork')
        self.assertEqual([record['id'] for record in found['records']], ['ok-1'])
        self.assertIsNone(self.metadata_value(reader, 'fts_query_errors'))


if __name__ == '__main__':
    unittest.main()
