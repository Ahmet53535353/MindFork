"""MMS-derived hygiene mechanisms: doctor reports plus opt-in hook signals.

Read-only for the vault: no model call, no network. The only writes are the
opt-in hook artifacts — soru cooldown markers and the touch log — under a
state directory that must stay outside the vault. The doctor never writes."""
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


class CompanionExemptionTest(unittest.TestCase):
    """#130 decision: tam muafiyet — companion memory files never enter a scan."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='v3-hygiene-companion-')
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.vault = root / 'vault'
        self.vault.mkdir()
        self.state = root / 'state'
        self.state.mkdir()
        self.companion = self.vault / '🔮 850-Companion'
        self.companion.mkdir()
        # A personalized directory name from the runtime bootstrap marker.
        (self.state / 'companion-bootstrap.json').write_text(
            json.dumps({'schema': 1, 'directory': '🔮 850-Companion'}), encoding='utf-8')
        (self.companion / 'Journal.md').write_text('gunluk ' * 600, encoding='utf-8')
        (self.companion / 'Last-Session.md').write_text('kart ' * 700, encoding='utf-8')

    def test_companion_files_never_counted_and_never_warned(self):
        scanned = hygiene.cap_scan(self.vault, state=self.state)
        self.assertEqual(scanned['over'], [])
        payload = {'hook_event_name': 'PostToolUse',
                   'tool_input': {'file_path': str(self.companion / 'Journal.md')}}
        self.assertEqual(hygiene.hook_cap_warning(self.vault, payload, harness='claude', state=self.state), '')
        # Without state the default companion name still applies.
        self.assertEqual(hygiene.cap_scan(self.vault)['over'], [])

    def test_companion_folder_never_asked_and_never_cold(self):
        then = time.time() - 60 * 86400
        os.utime(self.companion, (then, then))
        self.assertEqual(hygiene.folder_questions(self.vault, self.state, cooldown_days=14), [])
        self.assertFalse((self.state / 'soruldu').exists())
        promo = hygiene.promotion(self.vault, self.state)
        self.assertFalse([entry for entry in promo['cold'] if 'Companion' in entry['folder']])

    def test_companion_touch_never_logged(self):
        payload = {'hook_event_name': 'PostToolUse',
                   'tool_input': {'file_path': str(self.companion / 'Journal.md')}}
        hygiene.touch_log(self.state, self.vault, payload)
        self.assertFalse((self.state / 'touch-log.tsv').exists())

    def test_personalized_companion_directory_is_respected(self):
        import shutil
        shutil.rmtree(self.companion)  # a renamed bootstrap replaces the default folder
        other = self.vault / 'Aklım'
        other.mkdir()
        (other / 'Journal.md').write_text('not ' * 600, encoding='utf-8')
        (self.state / 'companion-bootstrap.json').write_text(
            json.dumps({'schema': 1, 'directory': 'Aklım'}), encoding='utf-8')
        self.assertEqual(hygiene.cap_scan(self.vault, state=self.state)['over'], [])
        self.assertEqual(hygiene.folder_questions(self.vault, self.state, cooldown_days=14), [])


class FolderQuestionsBudgetTest(unittest.TestCase):
    """#130: SessionStart never rglobs the vault — shallow mtimes only."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='v3-hygiene-soru-budget-')
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.state = self.root / 'state'
        self.state.mkdir()

    def test_deep_fresh_file_cannot_block_the_question(self):
        # A folder whose activity is only nested and old: the shallow scan reads
        # the folder stamp and its direct children, never the deep tree.
        (self.vault / 'Makaleler').mkdir()
        deep = self.vault / 'Makaleler/2026-09-27-konferans'
        deep.mkdir()
        (deep / 'not.md').write_text('# not\n', encoding='utf-8')
        then = time.time() - 60 * 86400
        os.utime(self.vault / 'Makaleler', (then, then))
        os.utime(deep, (then, then))
        questions = hygiene.folder_questions(self.vault, self.state, cooldown_days=14)
        self.assertEqual(len(questions), 1)
        self.assertIn('Makaleler', questions[0])

    def test_recent_nested_folder_keeps_a_folder_warm(self):
        # Gaining a new subfolder is top-level activity: the folder is not silent.
        (self.vault / 'Makaleler').mkdir()
        (self.vault / 'Makaleler/2026-09-27-konferans').mkdir()
        (self.vault / 'Makaleler/2026-09-27-konferans/yeni.md').write_text('# yeni\n', encoding='utf-8')
        self.assertEqual(hygiene.folder_questions(self.vault, self.state, cooldown_days=14), [])

    def test_top_level_activity_warms_the_folder(self):
        (self.vault / 'Makaleler').mkdir()
        (self.vault / 'Makaleler/konu.md').write_text('# konu\n', encoding='utf-8')
        self.assertEqual(hygiene.folder_questions(self.vault, self.state, cooldown_days=14), [])

    def test_generic_system_names_are_skipped_and_personal_names_are_not_in_code(self):
        for name in ('daily', 'knowledge', 'tasks', 'node_modules', 'scripts', 'tests', 'docs', 'template'):
            (self.vault / name).mkdir()
        questions = hygiene.folder_questions(self.vault, self.state, cooldown_days=14)
        self.assertEqual(questions, [])
        # The reviewer's finding 6: a user's personal layout (Finans/Müşteriler/gptpro)
        # must not be hard-coded; kasa-class names are covered by SENSITIVE_DIRS instead.
        source = hygiene.__dict__.get('SORU_SKIP_DIRS')
        self.assertIsNotNone(source)
        pattern = source.pattern
        for personal in ('Finans', 'Musteriler', 'Müşteriler', 'gptpro'):
            self.assertNotIn(personal, pattern)


class HarnessGateTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='v3-hygiene-harness-')
        self.addCleanup(tmp.cleanup)
        self.vault = Path(tmp.name)
        self.note = self.vault / 'not.md'
        self.note.write_text('kelime ' * 600, encoding='utf-8')
        self.payload = {'hook_event_name': 'PostToolUse', 'tool_input': {'file_path': str(self.note)}}

    def test_only_claude_and_codex_receive_the_warning(self):
        self.assertIn('Bolum SINYALI', hygiene.hook_cap_warning(self.vault, self.payload, harness='claude'))
        self.assertIn('Bolum SINYALI', hygiene.hook_cap_warning(self.vault, self.payload, harness='codex'))
        for harness in ('antigravity', 'opencode', 'omp', 'hermes'):
            self.assertEqual(hygiene.hook_cap_warning(self.vault, self.payload, harness=harness), '')


class TouchLogOptInTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='v3-hygiene-touch-')
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.vault = root / 'vault'
        self.vault.mkdir()
        self.state = root / 'state'
        self.state.mkdir()
        (self.vault / 'Notlar').mkdir()
        (self.vault / 'Notlar/a.md').write_text('# a\n', encoding='utf-8')

    def payload(self, path):
        return {'hook_event_name': 'PostToolUse', 'tool_input': {'file_path': str(path)}}

    def test_touch_log_and_promotion_roundtrip(self):
        hygiene.touch_log(self.state, self.vault, self.payload(self.vault / 'Notlar/a.md'))
        promo = hygiene.promotion(self.vault, self.state, days=30)
        self.assertEqual([entry['folder'] for entry in promo['hot']], ['Notlar'])

    def test_untouched_user_folder_is_cold_without_deep_scan(self):
        (self.vault / 'Beden').mkdir()
        os.utime(self.vault / 'Beden', (time.time() - 60 * 86400,) * 2)
        promo = hygiene.promotion(self.vault, self.state, days=30)
        self.assertEqual([entry['folder'] for entry in promo['cold']], ['Beden'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
