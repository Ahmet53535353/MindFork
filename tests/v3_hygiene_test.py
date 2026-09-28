"""Read-only doctor reports ported from MrMerkus/MMS: boundary and closed tasks.

Read-only for the vault: no model call, no network, no writes at all — the
doctor command must never mutate the vault or the runtime state."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import unicodedata

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
        for name in ('Finans', 'Şifre', 'Müşteriler', 'Özel', 'Maaşlar'):
            (self.vault / name).mkdir()
        report = hygiene.boundary(self.vault)
        self.assertEqual(sorted(report['sensitive_excluded']),
                         ['Finans', 'Maaşlar', 'Müşteriler', 'Özel', 'Şifre'])
        self.assertTrue(any(f.startswith('kasa_excluded:') for f in report['findings']))

    def test_sensitive_folder_with_long_note_stays_out_of_report_body(self):
        # The guarantee is name-based exclusion; nothing reads the folder contents here.
        (self.vault / 'Şifreler').mkdir()
        (self.vault / 'Şifreler/kasa.md').write_text('içerik ' * 600, encoding='utf-8')
        report = hygiene.boundary(self.vault)
        self.assertEqual(report['sensitive_excluded'], ['Şifreler'])
        self.assertFalse(any('kasa.md' in finding for finding in report['findings']))

    def test_real_folder_name_shapes_match_and_archives_are_not_kasa(self):
        # Maintainer regression: the anchored pattern missed prefixed, plural, upper-case
        # Turkish and NFD names, i.e. every folder shape the template itself uses.
        names = ['🔐 Kasa', '410-Şifreler', 'MÜŞTERİLER', 'GİZLİ', 'Kimlik Belgeleri',
                 unicodedata.normalize('NFD', 'Özel Notlar'), 'Private Notes']
        for name in names:
            self.assertTrue(hygiene.sensitive_excluded(name), name)
        for name in ('📦 900-Archive', 'Arşiv', '🏰 300-Projects', '🔮 850-Companion', 'Kasaba', 'Özellikler'):
            self.assertFalse(hygiene.sensitive_excluded(name), name)

    def test_walk_stops_at_code_trees_and_nested_repositories(self):
        (self.vault / '.obsidian').mkdir()
        (self.vault / 'app/node_modules/pkg/.git').mkdir(parents=True)
        (self.vault / 'clone/.git').mkdir(parents=True)
        (self.vault / 'clone/deep/inner/.git').mkdir(parents=True)
        (self.vault / 'worktree').mkdir()
        (self.vault / 'worktree/.git').write_text('gitdir: /elsewhere\n', encoding='utf-8')
        report = hygiene.boundary(self.vault)
        self.assertEqual(report['code_dirs'], ['app/node_modules'])
        self.assertEqual(report['nested_repositories'], ['clone', 'worktree'])

    def test_conflict_copy_needs_its_original(self):
        (self.vault / '.obsidian').mkdir()
        for name in ('Plan.md', 'Plan 2.md', 'Bolum 3.md', 'eski.bak'):
            (self.vault / name).write_text('x', encoding='utf-8')
        self.assertEqual(hygiene.boundary(self.vault)['backup_artifacts'], ['Plan 2.md', 'eski.bak'])


class ClosedTasksTest(unittest.TestCase):
    def test_tasks_written_by_v3_itself_are_found(self):
        # Maintainer regression: V3 writes JSON frontmatter ("status": "done"); the old
        # line pattern never matched a task created or updated through the CLI.
        state = Path(tempfile.mkdtemp(prefix='v3-hygiene-state-'))
        self.addCleanup(shutil.rmtree, state, True)
        env = dict(os.environ, BEYIN_V3_NO_SPAWN='1', PYTHONDONTWRITEBYTECODE='1')
        for name, status in (('bitti', 'done'), ('iptal', 'cancelled'), ('suren', 'active')):
            record = {'source': 'tasks/alt/' + name + '.md', 'text': '# ' + name + '\nstatus: done\n',
                      'metadata': {'id': name, 'status': status, 'owner': 'synthetic'}}
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/beyin_v3.py'), '--vault', str(self.vault),
                                     '--state', str(state), 'task-create', '--file', '-'],
                                    input=json.dumps(record), capture_output=True, text=True, encoding='utf-8',
                                    env=env, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.vault / 'tasks/alt/bitti.md').read_text(encoding='utf-8').startswith('---\n{'))
        now = time.time()
        for path in (self.vault / 'tasks/alt').glob('*.md'):
            os.utime(path, (now - 40 * 86400, now - 40 * 86400))
        before = {path: path.stat().st_mtime_ns for path in self.vault.rglob('*')}
        report = hygiene.closed_tasks(self.vault, days=30, now=now)
        self.assertEqual([entry['source'] for entry in report['closed']], ['tasks/alt/bitti.md', 'tasks/alt/iptal.md'])
        self.assertEqual(before, {path: path.stat().st_mtime_ns for path in self.vault.rglob('*')}, 'report only, never a move')

    def test_body_line_is_not_a_status(self):
        path = self.vault / 'tasks/not.md'
        path.write_text('---\nid: n\nstatus: active\n---\nstatus: done\n', encoding='utf-8')
        then = time.time() - 90 * 86400
        os.utime(path, (then, then))
        self.assertEqual(hygiene.closed_tasks(self.vault)['closed'], [])

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
        old.write_text('---\nid: e\nstatus: kapandı\n---\n# eski-tr\n', encoding='utf-8')
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
