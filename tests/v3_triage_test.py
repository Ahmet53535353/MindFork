"""Unit tests for triage and digestion routines (Issue #288 Item 3)."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE_SCRIPTS = str(ROOT / 'template/.claude/scripts')
if _TEMPLATE_SCRIPTS not in sys.path:
    sys.path.insert(0, _TEMPLATE_SCRIPTS)
_SCRIPTS = str(ROOT / 'scripts')
if _SCRIPTS not in sys.path:
    sys.path.append(_SCRIPTS)

import beyin_v3_triage as triage_module
from beyin_entry import human_result


class TriageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-triage-')
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name) / 'vault'
        self.vault.mkdir()
        self.state = Path(self.tmp.name) / 'state'
        self.state.mkdir()

        # Initialize mock runtime for beyin.py entry tests
        (self.vault / '.beyin-runtime.json').write_text(
            json.dumps({'state': str(self.state), 'schema': 1}), encoding='utf-8')
        (self.vault / '.beyin-version').write_text('3.10.0\n', encoding='utf-8')
        shutil.copy2(ROOT / 'scripts/beyin_entry.py', self.vault / 'beyin.py')

        claude_scripts = self.vault / '.claude' / 'scripts'
        claude_scripts.mkdir(parents=True)
        shutil.copy2(ROOT / 'scripts/beyin_v3.py', claude_scripts / 'beyin_v3_cli.py')
        for f in (ROOT / 'template/.claude/scripts').glob('*.py'):
            shutil.copy2(f, claude_scripts / f.name)

        # Reference timestamp: 2026-10-12 12:00:00 UTC
        self.now = datetime(2026, 10, 12, 12, 0, 0, tzinfo=timezone.utc).timestamp()

    def set_age(self, path: Path, days: float):
        t = self.now - (days * 86400)
        os.utime(path, (t, t))

    def test_inbox_scanning_with_varied_folder_names_and_sync_immunity(self):
        # 1. Emoji inbox folder (Batuhan review item #6)
        inbox1 = self.vault / '📥 000-Inbox'
        inbox1.mkdir(parents=True)
        # Note with frontmatter date 20 days ago, but mtime set to 1 day ago (simulating git sync / pull)
        f1 = inbox1 / 'capture-old.md'
        f1.write_text('---\ncreated: 2026-09-22\ntur: note\n---\nEski not.', encoding='utf-8')
        self.set_age(f1, 1)  # mtime is 1 day ago

        # 2. Kaynaklar folder (Batuhan review item #6)
        sources_folder = self.vault / 'Kaynaklar'
        sources_folder.mkdir(parents=True)
        f2 = sources_folder / 'report.pdf'
        f2.write_bytes(b'%PDF-dummy-content')
        self.set_age(f2, 5)

        # 3. Processed yakala card: should be ignored
        f3 = inbox1 / 'processed.md'
        f3.write_text('---\ntur: yakala\ndurum: islendi\n---\nIslenmis kart.', encoding='utf-8')
        self.set_age(f3, 10)

        # 4. Sensitive folder: must NEVER be scanned
        secret_box = self.vault / '🔐 Kasa' / 'inbox'
        secret_box.mkdir(parents=True)
        (secret_box / 'passwords.txt').write_text('secret', encoding='utf-8')

        report = triage_module.scan_inbox(self.vault, self.now)
        # Only f1 and f2 should be found
        self.assertEqual(report['count'], 2)
        paths = [item['path'] for item in report['items']]
        self.assertIn('📥 000-Inbox/capture-old.md', paths)
        self.assertIn('Kaynaklar/report.pdf', paths)
        self.assertNotIn('🔐 Kasa/inbox/passwords.txt', paths)

        # Sync immunity verification: f1 has frontmatter date 2026-09-22 (~20 days old), NOT 1 day!
        old_note = next(item for item in report['items'] if item['name'] == 'capture-old.md')
        self.assertGreaterEqual(old_note['age_days'], 19.0)

    def test_stale_tasks_detection_and_sync_immunity(self):
        tasks = self.vault / 'tasks'
        tasks.mkdir(parents=True)

        # 1. Fresh task (3 days old)
        t_fresh = tasks / 'fresh.md'
        t_fresh.write_text('---\nstatus: active\nupdated_at: 2026-10-09\n---\n# Taze Gorev\n- [ ] Is\n', encoding='utf-8')
        self.set_age(t_fresh, 3)

        # 2. Stale task: frontmatter updated_at is 25 days ago, but file mtime is fresh (sync checkout)
        t_stale = tasks / 'stale.md'
        t_stale.write_text('---\nstatus: open\nupdated_at: 2026-09-17\n---\n# Hareketsiz Gorev\n- [ ] Eski is\n', encoding='utf-8')
        self.set_age(t_stale, 1)  # mtime 1 day ago

        # 3. Completed task (25 days old, but closed)
        t_done = tasks / 'done.md'
        t_done.write_text('---\nstatus: completed\n---\n# Biten Gorev\n- [x] Bitti\n', encoding='utf-8')
        self.set_age(t_done, 25)

        # 4. Kapandi task (Turkish terminal status)
        t_kapandi = tasks / 'kapandi.md'
        t_kapandi.write_text('---\nstatus: kapandi\n---\n# Kapanan Gorev\n', encoding='utf-8')
        self.set_age(t_kapandi, 30)

        report = triage_module.scan_stale_tasks(self.vault, self.now, stale_days=14)
        self.assertEqual(report['open_count'], 2)
        self.assertEqual(report['stale_count'], 1)
        self.assertEqual(report['stale_tasks'][0]['title'], 'Hareketsiz Gorev')
        self.assertGreaterEqual(report['stale_tasks'][0]['age_days'], 24.0)

    def test_knowledge_digest_scanning(self):
        knowledge = self.vault / '🧠 500-Knowledge' / 'concepts'
        knowledge.mkdir(parents=True)

        k_recent = knowledge / 'sqlite-caching.md'
        k_recent.write_text('---\ntitle: SQLite Onbellek\nupdated_at: 2026-10-10\n---\nDetaylar...\n', encoding='utf-8')
        self.set_age(k_recent, 2)

        k_old = knowledge / 'legacy-db.md'
        k_old.write_text('---\ntitle: Eski DB\nupdated_at: 2026-08-01\n---\nDetaylar...\n', encoding='utf-8')
        self.set_age(k_old, 60)

        # outcomes.md in vault root
        outcomes = self.vault / 'outcomes.md'
        outcomes.write_text('# Outcomes\nSonuclar...\n', encoding='utf-8')
        self.set_age(outcomes, 4)

        report = triage_module.scan_knowledge_digest(self.vault, self.now, digest_days=7)
        self.assertEqual(report['count'], 2)
        titles = [item['title'] for item in report['items']]
        self.assertIn('SQLite Onbellek', titles)
        self.assertIn('Kazanimlar ve Sonuclar', titles)
        self.assertNotIn('Eski DB', titles)

    def test_companion_status_parsing(self):
        comp = self.vault / '🔮 850-Companion'
        comp.mkdir(parents=True)

        (comp / 'Kurallar.md').write_text(
            '# Kurallar\n\n- Kural 1\n* Kural 2\n1. Kural 3\n- Kural 4\n', encoding='utf-8')
        (comp / 'Threads.md').write_text(
            '## Threads\n### T1\n**Status:** active\n### T2\n**status:** active\n', encoding='utf-8')
        (comp / 'Last-Session.md').write_text(
            '# Son\n## 2026-10-12 06:30 · deneme · abcd1234\nDevir.\n', encoding='utf-8')

        # Presence file
        presence_dir = self.vault / '.presence'
        presence_dir.mkdir(parents=True)
        (presence_dir / 'agent-1.json').write_text(json.dumps({'heartbeat': self.now - 300}), encoding='utf-8')

        report = triage_module.scan_companion(self.vault, now=self.now)
        self.assertEqual(report['rules_count'], 4)
        self.assertEqual(report['active_threads'], 2)
        self.assertEqual(report['last_session'], '2026-10-12 06:30')
        self.assertEqual(report['active_presence'], 1)

    def test_triage_full_and_format_human(self):
        inbox = self.vault / '000-Inbox'
        inbox.mkdir(parents=True)
        f = inbox / 'quick-note.md'
        f.write_text('Fikir.', encoding='utf-8')
        self.set_age(f, 5)

        full_report = triage_module.triage(self.vault, stale_days=14, digest_days=7, now=self.now)
        self.assertEqual(full_report['schema'], 1)
        self.assertEqual(full_report['inbox']['count'], 1)

        human_text = triage_module.format_human(full_report)
        self.assertIn("=== Ikinci Beyin Sindirim ve Durum Raporu (Triage) ===", human_text)
        self.assertIn("[Gelen Kutusu / Yakalananlar]", human_text)
        self.assertIn("Bekleyen kaynak: 1", human_text)
        self.assertIn("[Sindirim Onerileri]", human_text)

    def test_cli_triage_json_output(self):
        cmd = [sys.executable, str(ROOT / 'scripts/beyin_v3.py'),
               '--vault', str(self.vault), '--state', str(self.state), 'triage']
        result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data.get('schema'), 1)
        self.assertIn('inbox', data)
        self.assertIn('tasks', data)
        self.assertIn('digest', data)
        self.assertIn('companion', data)
        self.assertIn('recommendations', data)

    def test_cli_human_via_beyin_entry(self):
        env = dict(os.environ, PYTHONIOENCODING='utf-8')
        cmd = [sys.executable, str(self.vault / 'beyin.py'), 'triage', '--human']
        result = subprocess.run(cmd, cwd=str(self.vault), env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("=== Ikinci Beyin Sindirim ve Durum Raporu (Triage) ===", result.stdout)


if __name__ == '__main__':
    unittest.main()
