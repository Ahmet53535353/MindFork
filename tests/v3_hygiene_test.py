"""Read-only doctor reports ported from MrMerkus/MMS: boundary and closed tasks.

Read-only for the vault: no model call, no network, no writes at all — the
doctor command must never mutate the vault or the runtime state."""
import importlib.util
import os
from pathlib import Path
import tempfile
import time
import unittest

ROOT = Path(os.environ.get('BEYIN_TEST_REPO', Path(__file__).resolve().parents[1]))
MODULE = ROOT / 'template/.claude/scripts' / 'beyin_v3_hygiene.py'
spec = importlib.util.spec_from_file_location('hygiene', MODULE)
hygiene = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hygiene)


class BoundaryTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='v3-hygiene-bound-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.vault = self.root / 'Beyin'
        self.vault.mkdir()

    def test_nested_repo_and_code_folder_are_named(self):
        (self.vault / '.obsidian').mkdir()
        sub = self.vault / 'sub'
        sub.mkdir()
        (sub / '.git').mkdir()
        (self.vault / 'node_modules').mkdir()
        report = hygiene.boundary(self.vault)
        self.assertEqual(report['status'], 'attention')
        joined = ' ; '.join(report['findings'])
        self.assertIn('nested_git_repository: sub', joined)
        self.assertIn('node_modules', joined)

    def test_also_flags_parent_obsidian_and_clean_vault_is_ok(self):
        (self.root / '.obsidian').mkdir()
        report = hygiene.boundary(self.vault)
        self.assertIn('parent', report['findings'][0])
        (self.root / '.obsidian').rmdir()
        (self.vault / '.obsidian').mkdir()
        self.assertEqual(hygiene.boundary(self.vault)['status'], 'ok')

    def test_turkish_diacritic_sensitive_folders_are_reported(self):
        # Regression for the PR review: diacritic names must match, not only ASCII.
        for name in ('Finans', 'Şifre', 'Müşteriler', 'Özel', 'Maşlar'):
            (self.vault / name).mkdir()
        report = hygiene.boundary(self.vault)
        self.assertEqual(sorted(report['sensitive_excluded']),
                         ['Finans', 'Maşlar', 'Müşteriler', 'Özel', 'Şifre'])
        self.assertTrue(any(f.startswith('kasa_excluded:') for f in report['findings']))

    def test_sensitive_folder_with_long_note_stays_out_of_report_body(self):
        # The guarantee is name-based exclusion; nothing reads the folder contents here.
        (self.vault / 'Arşiv').mkdir()
        (self.vault / 'Arşiv/kasa.md').write_text('içerik ' * 600)
        report = hygiene.boundary(self.vault)
        self.assertEqual(report['sensitive_excluded'], ['Arşiv'])
        self.assertFalse(any('kasa.md' in finding for finding in report['findings']))


class ClosedTasksTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='v3-hygiene-kapali-')
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name)
        (self.vault / 'tasks').mkdir()

    def test_old_done_task_listed_young_one_reported_as_not(self):
        old = self.vault / 'tasks/eski.md'
        old.write_text('---\nid: e\nstatus: done\n---\n# eski\n')
        fresh = self.vault / 'tasks/yeni.md'
        fresh.write_text('---\nid: y\nstatus: done\n---\n# yeni\n')
        now = time.time()
        os.utime(old, (now - 40 * 86400, now - 40 * 86400))
        os.utime(fresh, (now, now))
        report = hygiene.closed_tasks(self.vault, days=30, now=now)
        self.assertEqual([entry['source'] for entry in report['closed']], ['tasks/eski.md'])
        self.assertEqual(report['closed'][0]['days_old'], 40)

    def test_turkish_kapandi_status_is_recognized(self):
        old = self.vault / 'tasks/eski-tr.md'
        old.write_text('---\nid: e\nstatus: kapandı\n---\n# eski-tr\n')
        now = time.time()
        os.utime(old, (now - 45 * 86400, now - 45 * 86400))
        report = hygiene.closed_tasks(self.vault, days=30, now=now)
        self.assertEqual([entry['source'] for entry in report['closed']], ['tasks/eski-tr.md'])

    def test_active_tasks_never_listed_and_missing_folder_is_empty(self):
        active = self.vault / 'tasks/aktif.md'
        active.write_text('---\nid: a\nstatus: active\n---\n# aktif\n')
        then = time.time() - 90 * 86400
        os.utime(active, (then, then))
        self.assertEqual(hygiene.closed_tasks(self.vault)['closed'], [])
        self.assertEqual(hygiene.closed_tasks(self.vault / 'tasks')['closed_count'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
