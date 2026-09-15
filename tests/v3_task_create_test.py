"""Task-create regression for double-frontmatter and metadata loss."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'template/.claude/scripts'))
from beyin_v3_sync import SyncEngine, parse


class TaskCreateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name)/'vault'
        self.vault.mkdir()
        self.state = Path(self.tmp.name)/'state'
        self.engine = SyncEngine(self.vault, self.state)
        self.metadata = {'id': 'atlas-task', 'title': 'Prepare launch', 'status': 'active', 'owner': 'Synthetic Owner', 'project': 'atlas', 'visibility': 'internal', 'facts': {'reason': 'Approved synthetic task'}}

    def test_cli_creates_one_frontmatter_and_readbacks_all_task_fields(self):
        payload = {'source': 'tasks/atlas.md', 'text': 'Prepare the synthetic launch.', 'metadata': self.metadata}
        r = subprocess.run([sys.executable,str(ROOT/'scripts/beyin_v3.py'),'--vault',str(self.vault),'--state',str(self.state),'task-create'],input=json.dumps(payload),text=True,capture_output=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        record = json.loads(r.stdout)
        self.assertEqual(record['revision'], 1)
        self.assertEqual(record['kind'], 'task')
        for name, value in self.metadata.items():
            self.assertEqual(record[name], value)
        metadata, body = parse((self.vault/'tasks/atlas.md').read_text())
        self.assertEqual(metadata['status'], 'active')
        self.assertEqual(body, 'Prepare the synthetic launch.\n')
        self.assertEqual((self.vault/'tasks/atlas.md').read_text().count('---'), 2)

    def test_note_create_rejects_embedded_frontmatter_without_writes(self):
        with self.assertRaisesRegex(ValueError, 'frontmatter'):
            self.engine.note_create('notes/bad.md', '---\n{"status":"active"}\n---\nTask body', {'kind': 'fact'})
        self.assertFalse((self.vault/'notes/bad.md').exists())

    def test_note_create_requires_dedicated_task_command(self):
        with self.assertRaisesRegex(ValueError, 'task-create'):
            self.engine.note_create('notes/bad.md', 'Task body', {'kind': 'task'})
        self.assertFalse((self.vault/'notes/bad.md').exists())

    def test_invalid_required_task_metadata_never_writes(self):
        for patch in ({'id': ''}, {'owner': ''}, {'status': 'almost-done'}, {'revision': 2}):
            with self.subTest(patch=patch):
                with self.assertRaises(ValueError):
                    self.engine.task_create('tasks/bad.md', 'Task body', dict(self.metadata, **patch))
                self.assertFalse((self.vault/'tasks/bad.md').exists())

    def test_task_create_rejects_embedded_frontmatter_and_existing_file(self):
        with self.assertRaisesRegex(ValueError, 'frontmatter'):
            self.engine.task_create('tasks/bad.md', '---\nstatus: active\n---\nTask', self.metadata)
        self.engine.task_create('tasks/good.md', 'Original body', self.metadata)
        original = (self.vault/'tasks/good.md').read_bytes()
        with self.assertRaises(ValueError):
            self.engine.task_create('tasks/good.md', 'Overwrite', dict(self.metadata, id='other'))
        self.assertEqual((self.vault/'tasks/good.md').read_bytes(), original)

    def test_existing_double_frontmatter_task_is_not_partial_success(self):
        p = self.vault/'notes/legacy-bad.md'
        p.parent.mkdir()
        original = '---\n{"kind":"task"}\n---\n---\n{"id":"wrong-task","status":"active"}\n---\nTask body'
        p.write_text(original, encoding='utf-8')
        result = self.engine.sync()
        self.assertEqual(result['status'], 'degraded')
        self.assertTrue(self.engine.store.retrieve('Task body')['abstained'])
        self.assertEqual(p.read_text(), original)

if __name__ == '__main__':unittest.main()
