"""Reproduction tests for database URI credential redaction and note/task metadata protection."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))

from beyin_v3_secrets import redact
from beyin_v3_preferences import save
from beyin_v3_sync import SyncEngine


class TestSecretMetadataAndUri(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.vault = root / 'vault'
        self.vault.mkdir()
        self.state = root / 'state'
        self.state.mkdir()
        save(self.vault, {'secret_filter': True})
        self.engine = SyncEngine(self.vault, self.state)

    def test_database_uri_credentials_redaction(self):
        """Database connection strings with auth must have their credentials redacted."""
        fixtures = [
            ('postgres://user:password123@localhost:5432/mydb', 'password123', 'postgres://[REDACTED]@localhost:5432/mydb'),
            ('postgresql://admin:secret_pass@db.internal:5432/app', 'secret_pass', 'postgresql://[REDACTED]@db.internal:5432/app'),
            ('mysql://root:supersecret@127.0.0.1:3306/db', 'supersecret', 'mysql://[REDACTED]@127.0.0.1:3306/db'),
            ('mongodb+srv://appuser:clusterpass99@cluster0.mongodb.net/test', 'clusterpass99', 'mongodb+srv://[REDACTED]@cluster0.mongodb.net/test'),
            ('redis://:myredispass123@cache.host:6379/0', 'myredispass123', 'redis://[REDACTED]@cache.host:6379/0'),
            ('redis://appuser:myredispass123@cache.host:6379/0', 'myredispass123', 'redis://[REDACTED]@cache.host:6379/0'),
            ('amqp://guest:secretguest@localhost:5672/', 'secretguest', 'amqp://[REDACTED]@localhost:5672/'),
        ]
        for url, secret, expected in fixtures:
            with self.subTest(url=url):
                filtered, count = redact(url, self.state)
                self.assertGreaterEqual(count, 1, f"URI auth not redacted in: {url}")
                self.assertNotIn(secret, filtered)
                self.assertEqual(filtered, expected)

        clean_urls = [
            'https://normal-domain.com/path?query=value',
            'http://localhost:8080/health',
            'postgres://localhost:5432/mydb',
        ]
        for url in clean_urls:
            with self.subTest(clean_url=url):
                filtered, count = redact(url, self.state)
                self.assertEqual(count, 0)
                self.assertEqual(filtered, url)

    def test_note_create_metadata_redaction(self):
        """note_create must redact secrets in metadata fields (title, facts, etc.)."""
        db_pass = "synthetic_db_pass_123"
        token = "sk-" + ("SyntheticToken" * 2)
        metadata = {
            'title': f'Setup db postgres://admin:{db_pass}@db.local:5432/prod',
            'facts': {'api_key': token, 'environment': 'production'},
        }
        res = self.engine.note_create('notes/db.md', 'Clean note body text.', metadata=metadata)
        self.assertGreaterEqual(res.get('secrets_redacted', 0), 2)
        content = (self.vault / 'notes/db.md').read_text(encoding='utf-8')
        self.assertNotIn(db_pass, content)
        self.assertNotIn(token, content)
        self.assertIn('[REDACTED]', content)

        with self.engine.store._connect() as db:
            row = db.execute('SELECT r.payload FROM records r JOIN markdown_sources m ON r.id=m.id WHERE m.source="notes/db.md"').fetchone()
            self.assertIsNotNone(row)
            self.assertNotIn(db_pass, row[0])
            self.assertNotIn(token, row[0])

    def test_task_create_metadata_redaction(self):
        """task_create must redact secrets in metadata fields (title, next_action, facts)."""
        mysql_pass = "super_mysql_secret_99"
        redis_pass = "redis_secret_pass_88"
        metadata = {
            'id': 'task-service-deploy',
            'title': f'Migration mysql://root:{mysql_pass}@mysql.internal:3306/db',
            'status': 'active',
            'owner': 'ops-team',
            'next_action': f'Connect with redis://:{redis_pass}@redis.internal:6379/0',
            'facts': {'host': 'prod-server'},
        }
        res = self.engine.task_create('tasks/deploy.md', 'Clean task body.', metadata=metadata)
        self.assertGreaterEqual(res.get('secrets_redacted', 0), 2)
        content = (self.vault / 'tasks/deploy.md').read_text(encoding='utf-8')
        self.assertNotIn(mysql_pass, content)
        self.assertNotIn(redis_pass, content)
        self.assertIn('[REDACTED]', content)

        with self.engine.store._connect() as db:
            row = db.execute('SELECT payload FROM records WHERE id="task-service-deploy"').fetchone()
            self.assertIsNotNone(row)
            self.assertNotIn(mysql_pass, row[0])
            self.assertNotIn(redis_pass, row[0])

    def test_update_task_changes_redaction(self):
        """update_task must redact secrets in changes dictionary."""
        # First create a clean task
        init_metadata = {
            'id': 'task-update-target',
            'title': 'Original clean task title',
            'status': 'inbox',
            'owner': 'developer',
        }
        self.engine.task_create('tasks/target.md', 'Clean task body.', metadata=init_metadata)

        secret_pass = "synthetic_task_pass_777"
        changes = {
            'status': 'active',
            'next_action': f'password={secret_pass}',
            'facts': {'conn': 'postgres://admin:pgsecretpass@host:5432/app'},
        }
        updated = self.engine.update_task('task-update-target', 1, changes)
        self.assertGreaterEqual(updated.get('secrets_redacted', 0), 2)

        content = (self.vault / 'tasks/target.md').read_text(encoding='utf-8')
        self.assertNotIn(secret_pass, content)
        self.assertNotIn('pgsecretpass', content)
        self.assertIn('[REDACTED]', content)

        with self.engine.store._connect() as db:
            row = db.execute('SELECT payload FROM records WHERE id="task-update-target"').fetchone()
            self.assertIsNotNone(row)
            self.assertNotIn(secret_pass, row[0])
            self.assertNotIn('pgsecretpass', row[0])


if __name__ == '__main__':
    unittest.main()
