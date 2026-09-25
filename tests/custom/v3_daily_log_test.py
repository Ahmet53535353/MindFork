"""Daily session log (daily/log/) — model-free B1. Spec: docs/specs/2026-09-26-daily-log-design.md."""
import datetime as dt
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'template/.claude/scripts'
HOOK = SCRIPTS / 'beyin_v3_hook.py'

SETTINGS_OFF = dict(auto_sync=True, interval_minutes=0, context_mode='turn',
                    context_chars=5000, secret_filter=False, daily_log=False)
SETTINGS_ON = dict(SETTINGS_OFF, daily_log=True)


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


def key_of(session_id):
    return hashlib.sha256(str(session_id).encode()).hexdigest()[:24]


def at(day, hour, minute):
    return dt.datetime.fromisoformat(f'{day}T{hour:02d}:{minute:02d}:00').timestamp()


class DailyLogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load('daily_log_subject', 'beyin_v3_sessionlog.py')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-daily-log-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.state = self.root / 'state'
        self.state.mkdir()
        sys.path.insert(0, str(SCRIPTS))
        self.addCleanup(lambda: str(SCRIPTS) in sys.path and sys.path.remove(str(SCRIPTS)))
        self.today = dt.date.today().isoformat()

    def log_text(self, day=None):
        path = self.vault / 'daily/log' / f'{day or self.today}.md'
        return path.read_text(encoding='utf-8') if path.exists() else None

    def start(self, session, settings=SETTINGS_ON, when=None):
        return self.module.session_start(self.vault, self.state, settings, 'codex', session,
                                         now=when or at(self.today, 14, 32))

    def end(self, session, settings=SETTINGS_ON, when=None):
        return self.module.session_end(self.vault, self.state, settings, 'codex', session,
                                       now=when or at(self.today, 15, 10))

    def test_gate_off_writes_and_injects_nothing(self):
        reminder = self.start('s1', SETTINGS_OFF)
        self.end('s1', SETTINGS_OFF)
        self.assertIsNone(reminder)
        self.assertIsNone(self.log_text())
        self.assertEqual(list(self.state.glob('sessionlog_start.*')), [])

    def test_open_block_closes_with_span_and_prompt_count(self):
        self.start('s2')
        (self.state / f'prompt_count.{key_of("s2")}').write_text('23\n')
        self.end('s2')
        text = self.log_text()
        self.assertIn('"type": "episodic"', text)
        self.assertNotIn('## OPEN', text)
        self.assertIn('## 14:32–15:10 · codex · 23 istem', text)
        self.assertIn('<!-- beyin-session:' + key_of('s2'), text)
        self.assertIn('### Özet', text)

    def test_agent_summary_survives_session_end(self):
        self.start('s3')
        path = self.vault / 'daily/log' / f'{self.today}.md'
        path.write_text(path.read_text(encoding='utf-8') + '\n## Bağlam\ntest oturumu\n', encoding='utf-8')
        self.end('s3')
        text = self.log_text()
        self.assertIn('test oturumu', text)
        self.assertEqual(text.count('## Bağlam'), 1)

    def test_receipts_inside_window_are_referenced(self):
        import time as _time
        from beyin_v3_sync import SyncEngine
        engine = SyncEngine(self.vault, self.state)
        self.addCleanup(engine.store.close)
        self.start('s4', when=_time.time() - 3600)
        (self.vault / 'notes').mkdir(exist_ok=True)
        (self.vault / 'notes/x.md').write_text('x', encoding='utf-8')
        engine.receipt('daily-log-evt', 'görev X tamamlandı', ['notes/x.md'], 'codex')
        self.end('s4', when=_time.time())
        text = self.log_text()
        self.assertIn('görev X tamamlandı', text)
        self.assertIn('receipts/', text)

    def test_orphaned_session_is_marked_on_next_start(self):
        self.start('s5', when=at(self.today, 9, 0))  # opens, never closes
        self.start('s6', when=at(self.today, 18, 0))  # 9h later: s5 is dead by TTL
        text = self.log_text()
        self.assertIn('OPEN (yarıda kaldı)', text)
        self.assertTrue((self.state / f'sessionlog_start.{key_of("s6")}').exists())
        self.assertFalse((self.state / f'sessionlog_start.{key_of("s5")}').exists())

    def test_two_sessions_two_blocks(self):
        self.start('s7a', when=at(self.today, 9, 0))
        self.start('s7b', when=at(self.today, 9, 5))
        self.end('s7a', when=at(self.today, 9, 30))
        # s7b still open while s7a closed; second end must not touch the other block
        self.end('s7b', when=at(self.today, 10, 0))
        text = self.log_text()
        self.assertIn('## 09:00–09:30', text)
        self.assertIn('## 09:05–10:00', text)

    def test_same_session_restart_does_not_duplicate_block(self):
        self.start('s8')
        self.start('s8')  # harness retry of SessionStart
        text = self.log_text()
        self.assertEqual(text.count(key_of('s8')), 1)


class DailyLogHookWiringTest(unittest.TestCase):
    """The hook must open the block on SessionStart, inject the reminder line there only,
    and close it on SessionEnd — synchronous writes, independent of the queue worker."""

    @classmethod
    def setUpClass(cls):
        cls.module = load('daily_log_hook_subject', 'beyin_v3_sessionlog.py')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-daily-log-hook-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.state = self.root / 'state'
        self.state.mkdir()
        home = self.root / 'home'
        home.mkdir()
        self.env = dict(HOME=str(home), USERPROFILE=str(home), PATH=os.defpath,
                        TEMP=str(self.root), TMP=str(self.root), PYTHONIOENCODING='utf-8',
                        PYTHONDONTWRITEBYTECODE='1', BEYIN_V3_NO_SPAWN='1',
                        PYTHONPATH=str(SCRIPTS))
        sys.path.insert(0, str(SCRIPTS))
        self.addCleanup(lambda: str(SCRIPTS) in sys.path and sys.path.remove(str(SCRIPTS)))

    def preferences(self, daily_log):
        from beyin_v3_preferences import save
        save(self.vault, dict(SETTINGS_ON, daily_log=daily_log))

    def invoke(self, event, session):
        payload = {'hook_event_name': event, 'session_id': session, 'event_id': event + '-' + session,
                   'cwd': str(self.vault), 'prompt': 'daily log denemesi'}
        result = subprocess.run([sys.executable, str(HOOK), '--vault', str(self.vault),
                                 '--state', str(self.state), '--harness', 'codex'],
                                input=json.dumps(payload), text=True, capture_output=True,
                                cwd=str(self.vault), env=self.env, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def context_of(self, stdout):
        output = json.loads(stdout.strip().splitlines()[-1])
        return output.get('hookSpecificOutput', {}).get('additionalContext', '')

    def test_hook_gates_reminder_to_session_start(self):
        self.preferences(False)
        self.assertNotIn('Günlük log', self.context_of(self.invoke('SessionStart', 'wire-off')))
        self.preferences(True)
        self.assertIn('Özet', self.context_of(self.invoke('SessionStart', 'wire-on')))
        (self.vault / 'daily/log').mkdir(parents=True, exist_ok=True)
        log = next((self.vault / 'daily/log').glob('*.md'))
        self.assertIn('## OPEN', log.read_text(encoding='utf-8'))
        self.invoke('SessionEnd', 'wire-on')
        self.assertNotIn('## OPEN', log.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
