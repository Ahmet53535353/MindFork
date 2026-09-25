"""SyncEngine writes must maintain records_fts: derived-write spine (external review P0)."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'template/.claude/scripts'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


class FtsSyncSpineTest(unittest.TestCase):
    def setUp(self):
        self.sync_module = load('spine_sync', 'beyin_v3_sync.py')
        self.runtime = load('spine_runtime', 'beyin_v3.py')
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-fts-spine-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.engine = self.sync_module.SyncEngine(self.vault, self.root / 'runtime')
        self.store = self.engine.store
        self.addCleanup(lambda: self.store.close())

    def write(self, body='Nebula calibration StripeWebhookHandler handler.\n', name='notes/not.md'):
        metadata = {'id': 'spine-note', 'kind': 'note', 'project': 'nebula', 'revision': 1,
                    'status': 'active', 'visibility': 'internal', 'facts': {}}
        path = self.vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('---\n' + json.dumps(metadata) + '\n---\n' + body, encoding='utf-8')
        return path

    def fts_ids(self, token):
        with sqlite3.connect(self.store.database) as db:
            return [row[0] for row in db.execute(
                "SELECT id FROM records_fts WHERE records_fts MATCH ?", ('"' + token + '"',))]

    def records_count(self, table):
        with sqlite3.connect(self.store.database) as db:
            return db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]

    def test_sync_add_edit_delete_follows_fts(self):
        path = self.write()
        self.engine.sync()
        self.assertEqual(self.fts_ids('StripeWebhookHandler'), ['spine-note'])  # add indexes

        path.write_text(path.read_text(encoding='utf-8').replace(
            'Nebula calibration StripeWebhookHandler handler.', 'Zirkon kova ozeti satiri.'), encoding='utf-8')
        self.engine.sync()
        self.assertEqual(self.fts_ids('StripeWebhookHandler'), [])  # edit refreshes
        self.assertEqual(self.fts_ids('Zirkon'), ['spine-note'])

        path.unlink()
        self.engine.sync()
        self.assertEqual(self.records_count('records'), 0)
        self.assertEqual(self.records_count('records_fts'), 0)  # delete leaves no orphan

    def test_legacy_drifted_database_self_heals_on_open(self):
        # Shape of a pre-fix vault: records carry fresh payloads while the frozen FTS
        # snapshot lags and no fts_params signature exists. Rebuild must repair once.
        self.write()
        self.engine.sync()
        with sqlite3.connect(self.store.database) as db:  # legacy drift: index lags behind
            record = json.loads(db.execute("SELECT payload FROM records WHERE id='spine-note'").fetchone()[0])
            record['text'] = 'Zirkon kova yeni metin'
            db.execute("UPDATE records SET payload=? WHERE id='spine-note'", (json.dumps(record),))
            db.execute("DELETE FROM records_fts")
            db.execute("INSERT INTO records_fts(id, type, project, text, facts) VALUES (?,?,?,?,?)",
                       ('spine-note', '', 'nebula', 'Nebula calibration StripeWebhookHandler handler.', ''))
            db.commit()
        self.store.close()
        reopened = self.runtime.MemoryStore(self.root / 'runtime', self.vault)
        self.addCleanup(lambda: reopened.close())
        with sqlite3.connect(reopened.database) as db:
            params = db.execute("SELECT value FROM metadata WHERE key='fts_params'").fetchone()
        self.assertIsNotNone(params)  # signature written by the rebuild
        self.assertEqual(self.fts_ids('Zirkon'), ['spine-note'])
        self.assertEqual(self.fts_ids('StripeWebhookHandler'), [])

    def test_doctor_reports_fts_consistency(self):
        # The real doctor surface is the root CLI; it must expose the consistency probe.
        import subprocess
        self.write()
        self.engine.sync()
        result = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/beyin_v3.py'), '--vault', str(self.vault),
             '--state', str(self.root / 'runtime'), 'doctor'],
            capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        consistency = json.loads(result.stdout)['fts_consistency']
        self.assertEqual(consistency, {'records': 1, 'indexed': 1, 'orphans': 0})

    def test_context_for_rejects_invalid_types_immediately(self):
        # Fallback re-validation already protects the contract; dispatch must still
        # fail fast before any passage/index work.
        with self.assertRaises(ValueError):
            self.store.context_for('claude', 'nebula calibration', strict=True, types='bogus')


if __name__ == '__main__':
    unittest.main()
