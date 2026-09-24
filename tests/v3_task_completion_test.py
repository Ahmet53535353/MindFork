"""Opt-in completion contracts use only synthetic vault sources."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))
from beyin_v3_sync import SyncEngine, parse


class TaskCompletionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-task-completion-')
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name) / 'vault'
        self.vault.mkdir()
        self.state = Path(self.tmp.name) / 'state'
        self.engine = SyncEngine(self.vault, self.state)
        self.metadata = {'id': 'synthetic-task', 'title': 'Inspect calibration',
                         'owner': 'Synthetic Reviewer', 'status': 'active',
                         'completion_contract': 'strict',
                         'completion_criterion': 'A reviewed calibration result is recorded.'}

    def doctor(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/beyin_v3.py'),
                                 '--vault', str(self.vault), '--state', str(self.state), 'doctor'],
                                capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_strict_create_requires_criterion_and_done_evidence_before_write(self):
        for patch, message in [({'completion_criterion': ''}, 'completion_criterion'),
                               ({'status': 'done'}, 'evidence_refs'),
                               ({'completion_contract': 'unknown'}, 'completion_contract')]:
            with self.subTest(patch=patch), self.assertRaisesRegex(ValueError, message):
                self.engine.task_create('tasks/synthetic.md', 'Inspect calibration.',
                                        dict(self.metadata, **patch))
            self.assertFalse((self.vault / 'tasks/synthetic.md').exists())
        created = self.engine.task_create('tasks/synthetic.md', 'Inspect calibration.', self.metadata)
        self.assertEqual(created['completion_contract'], 'strict')
        self.assertEqual(created['revision'], 1)

    def test_strict_done_rejects_missing_or_invalid_refs_without_mutation(self):
        self.engine.task_create('tasks/synthetic.md', 'Keep this task body.', self.metadata)
        task = self.vault / 'tasks/synthetic.md'
        before = task.read_bytes()
        for refs in ([], ['notes/missing.md'], ['../outside.md'],
                     ['notes/missing.md'] * 2, ['tasks/synthetic.md']):
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                self.engine.update_task('synthetic-task', 1,
                                        {'status': 'done', 'evidence_refs': refs})
            self.assertEqual(task.read_bytes(), before)
            self.assertEqual(len(self.engine.store.history('synthetic-task')), 1)
        self.assertEqual(list((self.state / 'markdown-journal').glob('*.json')), [])

        evidence = self.engine.note_create('notes/calibration-result.md',
                                           'Synthetic calibration result reviewed.', {'kind': 'fact'})
        self.assertEqual(evidence['status'], 'succeeded')
        updated = self.engine.update_task('synthetic-task', 1,
                                          {'status': 'done', 'evidence_refs': ['notes/calibration-result.md']})
        self.assertEqual(updated['revision'], 2)
        self.assertEqual(updated['status'], 'done')
        self.assertEqual(updated['evidence_refs'], ['notes/calibration-result.md'])
        metadata, body = parse(task.read_text(encoding='utf-8'))
        self.assertEqual(metadata['completion_criterion'], self.metadata['completion_criterion'])
        self.assertEqual(body, 'Keep this task body.\n')
        self.assertEqual(self.doctor()['task_completion']['strict_issue_count'], 0)

    def test_strict_contract_cannot_be_removed_during_done_transition(self):
        self.engine.task_create('tasks/synthetic.md', 'Inspect calibration.', self.metadata)
        task = self.vault / 'tasks/synthetic.md'
        before = task.read_bytes()
        with self.assertRaisesRegex(ValueError, 'cannot be removed'):
            self.engine.update_task('synthetic-task', 1,
                                    {'completion_contract': None, 'status': 'done'})
        self.assertEqual(task.read_bytes(), before)
        self.assertEqual(len(self.engine.store.history('synthetic-task')), 1)

    def test_cancelled_and_legacy_tasks_keep_existing_status_behavior(self):
        self.engine.task_create('tasks/strict.md', 'Strict task.', self.metadata)
        cancelled = self.engine.update_task('synthetic-task', 1, {'status': 'cancelled'})
        self.assertEqual(cancelled['status'], 'cancelled')
        legacy = self.engine.task_create('tasks/legacy.md', 'Legacy task.',
                                         {'id': 'legacy-task', 'owner': 'Synthetic Reviewer', 'status': 'done'})
        self.assertEqual(legacy['status'], 'done')
        report = self.doctor()['task_completion']
        self.assertEqual(report['strict_issue_count'], 0)
        self.assertEqual(report['legacy_done_count'], 1)
        self.assertEqual(report['legacy_done'][0]['id'], 'legacy-task')
        reopened = self.engine.update_task('legacy-task', 1, {'status': 'waiting'})
        self.assertEqual(reopened['revision'], 2)
        self.assertEqual(reopened['status'], 'waiting')

    def test_doctor_flags_manual_strict_done_without_evidence_and_lost_ref(self):
        self.engine.task_create('tasks/synthetic.md', 'Strict task.', self.metadata)
        task = self.vault / 'tasks/synthetic.md'
        metadata, body = parse(task.read_text(encoding='utf-8'))
        metadata['status'] = 'done'
        task.write_text('---\n' + json.dumps(metadata) + '\n---\n' + body, encoding='utf-8')
        self.assertEqual(self.engine.sync()['status'], 'succeeded')
        report = self.doctor()
        self.assertEqual(report['status'], 'needs_attention')
        self.assertEqual(report['task_completion']['strict_issue_count'], 1)
        self.assertIn('evidence_refs', report['task_completion']['strict_issues'][0]['reason'])

        (self.vault / 'notes').mkdir()
        source = self.vault / 'notes/result.md'
        source.write_text('Synthetic result.\n', encoding='utf-8')
        metadata['evidence_refs'] = ['notes/result.md']
        task.write_text('---\n' + json.dumps(metadata) + '\n---\n' + body, encoding='utf-8')
        self.engine.sync()
        self.assertEqual(self.doctor()['task_completion']['strict_issue_count'], 0)
        source.unlink()
        report = self.doctor()['task_completion']
        self.assertEqual(report['strict_issue_count'], 1)
        self.assertIn('existing vault source', report['strict_issues'][0]['reason'])
        current = self.engine.store.retrieve('Strict task')['records'][0]
        reopened = self.engine.update_task('synthetic-task', current['revision'],
                                           {'status': 'active', 'evidence_refs': []})
        self.assertEqual(reopened['status'], 'active')
        self.assertEqual(self.doctor()['task_completion']['strict_issue_count'], 0)

    def test_doctor_reports_unavailable_task_source_without_crashing(self):
        (self.vault / 'notes').mkdir()
        (self.vault / 'notes/result.md').write_text('Synthetic result.\n', encoding='utf-8')
        self.engine.task_create('tasks/synthetic.md', 'Strict task.', self.metadata)
        self.engine.update_task('synthetic-task', 1,
                                {'status': 'done', 'evidence_refs': ['notes/result.md']})
        original_path = self.engine._path

        def unavailable_task_source(relative, existing=False):
            if relative == 'tasks/synthetic.md':
                raise ValueError('symlink source rejected')
            return original_path(relative, existing=existing)

        with patch.object(self.engine, '_path', side_effect=unavailable_task_source):
            report = self.engine.completion_health()
        self.assertEqual(report['strict_issue_count'], 1)
        self.assertIn('task source is unavailable', report['strict_issues'][0]['reason'])


if __name__ == '__main__':
    unittest.main()
