"""Opt-in write-path secret filtering; all fixtures are synthetic."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'template/.claude/scripts'))
from beyin_v3_preferences import save
from beyin_v3_secrets import redact
from beyin_v3_sync import SyncEngine


class SecretFilterTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.vault = root/'vault'; self.vault.mkdir()
        self.state = root/'state'
        self.engine = SyncEngine(self.vault, self.state)
        self.token = 'sk-' + ('SyntheticOnly' * 3)

    def test_default_off_preserves_text(self):
        result = self.engine.note_create('notes/default.md', 'Demo '+self.token)
        self.assertEqual(result['secrets_redacted'], 0)
        self.assertIn(self.token, (self.vault/'notes/default.md').read_text())

    def test_enabled_filter_redacts_all_three_write_paths_and_reports_health(self):
        save(self.vault, {'secret_filter': True})
        reference = self.vault/'reference.md'; reference.write_text('Synthetic reference.\n')
        self.engine.sync()
        note = self.engine.note_create('notes/filtered.md', 'Demo '+self.token)
        task = self.engine.task_create('tasks/filtered.md', 'Bearer '+'x'*24,
            {'id':'filtered-task','title':'Synthetic','status':'active','owner':'Synthetic Owner'})
        receipt = self.engine.receipt('filtered-event', 'api_key='+self.token,
                                      ['reference.md'], 'codex')
        for result in (note, task, receipt):
            self.assertGreaterEqual(result['redacted'], 1)
            self.assertNotIn(self.token, (self.vault/result['source']).read_text())
            self.assertIn('[REDACTED]', (self.vault/result['source']).read_text())
        doctor = subprocess.run([sys.executable, str(ROOT/'scripts/beyin_v3.py'), '--vault', str(self.vault),
                                 '--state', str(self.state), 'doctor'], capture_output=True, text=True)
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        self.assertGreaterEqual(json.loads(doctor.stdout)['secret_filter']['total'], 3)
        from beyin_v3_hook import drain_queue
        drain_queue(self.vault, self.state)
        hook_health = json.loads((self.state/'hook-health.json').read_text(encoding='utf-8'))
        self.assertGreaterEqual(hook_health['sync']['secrets_redacted'], 3)

    def test_builtin_patterns_cover_documented_token_families(self):
        values = [
            'ghp_' + 'A'*24,
            'github_pat_' + 'B'*24,
            'sk-' + 'C'*24,
            'AKIA' + 'D'*16,
            'Bearer ' + 'e'*24,
            'password=synthetic-password',
            '-----BEGIN PRIVATE KEY-----\nSYNTHETIC\n-----END PRIVATE KEY-----',
        ]
        filtered, count = redact('\n'.join(values), self.state)
        self.assertEqual(count, len(values))
        self.assertNotIn('SYNTHETIC', filtered)
        self.assertEqual(filtered.count('[REDACTED]'), len(values))
        clean = 'Temiz bir Turkce ve English sentence; anahtar degeri icermiyor.'
        self.assertEqual(redact(clean, self.state), (clean, 0))

    def test_custom_state_literal_is_redacted_and_never_written_to_health(self):
        save(self.vault, {'secret_filter': True})
        self.state.mkdir(parents=True, exist_ok=True)
        literal = 'CUSTOM-SYNTHETIC-CANARY'
        (self.state/'secret-patterns.txt').write_text(literal+'\n', encoding='utf-8')
        result = self.engine.note_create('knowledge/custom.md', 'Value '+literal)
        self.assertEqual(result['secrets_redacted'], 1)
        self.assertNotIn(literal, (self.vault/'knowledge/custom.md').read_text())
        database = (self.state/'secret-filter.sqlite3').read_bytes()
        self.assertNotIn(literal.encode(), database)


if __name__ == '__main__': unittest.main()
