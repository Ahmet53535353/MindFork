"""Global boundary adapters exercised in isolated homes, never user hook settings."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'template/.claude/scripts'
sys.path.insert(0, str(SCRIPTS))
import beyin_v3_bridge as bridge
import beyin_v3_hook as hook
from beyin_v3_sync import SyncEngine


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.vault = self.root / 'Brain Space'; self.vault.mkdir()
        self.state = self.root / 'state'
        self.project = self.root / 'Projects' / 'Örnek Space'; self.project.mkdir(parents=True)
        self.home = self.root / 'home'; self.home.mkdir()
        self.env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home),
                        BEYIN_V3_NO_SPAWN='1', PYTHONDONTWRITEBYTECODE='1', PYTHONIOENCODING='utf-8')
        self.payload = dict(hook_event_name='SessionStart', session_id='one-session', event_id='start',
                            cwd=str(self.project), prompt='TRANSCRIPT_CANARY')

    def invoke(self, payload=None, extra=(), harness='codex', script=None, cwd=None):
        command = [sys.executable, str(script or SCRIPTS / 'beyin_v3_bridge.py'),
                   '--vault', str(self.vault), '--state', str(self.state), '--harness', harness,
                   '--project-root', str(self.root / 'Projects'), *extra]
        result = subprocess.run(command, input=json.dumps(self.payload if payload is None else payload),
                                text=True, encoding='utf-8', capture_output=True, env=self.env,
                                cwd=cwd or self.project, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def queued(self):
        return [json.loads(p.read_text(encoding='utf-8')) for p in (self.state / 'hook-queue').glob('*.json')]

    def test_external_boundary_context_and_project_metadata_for_both_clients(self):
        for harness in ('claude', 'codex'):
            result = self.invoke(harness=harness)
            text = result['hookSpecificOutput']['additionalContext']
            self.assertIn('receipt --harness ' + harness, text)
            self.assertIn(str(self.vault / 'beyin.py'), text)
            self.assertLessEqual(len(text), 1500)
        events = self.queued()
        self.assertEqual(len(events), 2)
        for event in events:
            self.assertEqual(event['project'], self.project.name)
            self.assertEqual(len(event['project_id']), 24)
        self.assertNotIn(str(self.project), json.dumps(events))
        self.assertNotIn('TRANSCRIPT_CANARY', json.dumps(events))

    def test_vault_subdirectory_and_other_installed_vault_skip_duplicates(self):
        for cwd in (self.vault, self.vault / 'nested', self.project):
            cwd.mkdir(exist_ok=True)
            if cwd == self.project: (cwd / '.beyin-runtime.json').write_text('{}')
            self.assertEqual(self.invoke(dict(self.payload, cwd=str(cwd)),
                                        extra=['--project-root', str(self.root)]), {})
        self.assertEqual(self.queued(), [])

    def test_allowlist_sibling_prefix_and_symlink_escape_are_not_authorized(self):
        sibling = self.root / 'Projects-elsewhere'; sibling.mkdir()
        self.assertEqual(self.invoke(dict(self.payload, cwd=str(sibling))), {})
        link = self.project / 'outside'
        try: link.symlink_to(sibling, target_is_directory=True)
        except OSError: pass  # Native Windows without symlink permission still tests prefix boundary.
        else: self.assertEqual(self.invoke(dict(self.payload, cwd=str(link))), {})
        self.assertEqual(self.queued(), [])

    def test_unsupported_events_no_memory_internal_and_manual_are_inert(self):
        for event in ('UserPromptSubmit', 'PostToolUse', 'Unexpected'):
            self.assertEqual(self.invoke(dict(self.payload, hook_event_name=event)), {})
        self.assertEqual(self.invoke(dict(self.payload, no_memory=True)), {})
        self.env['BEYIN_V3_INTERNAL'] = '1'
        self.assertEqual(self.invoke(), {})
        del self.env['BEYIN_V3_INTERNAL']
        (self.vault / '.beyin-preferences.json').write_text('{"auto_sync": false}')
        self.assertEqual(self.invoke(), {})
        self.assertEqual(self.queued(), [])

    def test_public_skip_guard_is_inert(self):
        self.env['BEYIN_V3_SKIP'] = '1'
        self.assertEqual(self.invoke(), {})
        self.assertEqual(self.queued(), [])

    def test_public_skip_guard_honours_only_exact_one(self):
        for count, value in enumerate(('0', 'false', ''), start=1):
            with self.subTest(value=value):
                self.env['BEYIN_V3_SKIP'] = value
                result = self.invoke(dict(self.payload, event_id='start-%d' % count))
                self.assertIn('receipt --harness codex', result['hookSpecificOutput']['additionalContext'])
                self.assertEqual(len(self.queued()), count)

    def test_independent_budget_events_and_local_context_off(self):
        for budget in ('0', '20'):
            self.assertEqual(self.invoke(extra=['--context-chars', budget]), {})
        self.assertEqual(len(self.queued()), 1)
        self.assertEqual(self.invoke(extra=['--event', 'SessionEnd']), {})
        (self.vault / '.beyin-preferences.json').write_text('{"context_mode": "off"}')
        self.assertEqual(self.invoke(), {})

    def test_same_event_and_session_ids_in_different_projects_do_not_collide(self):
        self.invoke(); self.invoke()
        other = self.root / 'Projects' / 'second' / self.project.name; other.mkdir(parents=True)
        self.invoke(dict(self.payload, cwd=str(other)))
        events = self.queued()
        self.assertEqual(len(events), 2)
        self.assertEqual(len({e['session'] for e in events}), 2)
        self.assertEqual(len({e['project_id'] for e in events}), 2)

    def test_global_start_never_injects_companion_or_receipts(self):
        self.state.mkdir()
        (self.state / 'jev.json').write_text('{"mode":"on","features":["auto_context"]}')
        (self.vault / 'receipts').mkdir()
        (self.vault / 'receipts/private.md').write_text('PRIVATE_VAULT_CANARY')
        result = self.invoke()
        self.assertNotIn('PRIVATE_VAULT_CANARY', json.dumps(result))
        self.assertFalse((self.state / 'jev-calls.jsonl').exists())

    def test_unknown_session_cannot_mix_unrelated_receipt_checkpoints(self):
        for session in ('', 'unknown', None, 1):
            self.assertEqual(self.invoke(dict(self.payload, session_id=session)), {})
        self.assertEqual(self.queued(), [])

    def test_cwd_environment_and_process_fallback(self):
        payload = {k: v for k, v in self.payload.items() if k != 'cwd'}
        self.env['CLAUDE_PROJECT_DIR'] = str(self.project)
        self.assertIn('hookSpecificOutput', self.invoke(payload, harness='claude', cwd=self.home))
        self.assertIn('hookSpecificOutput', self.invoke(payload, harness='codex'))
        self.assertEqual(self.invoke(dict(self.payload, cwd=123)), {})

    def test_gap_projection_preserves_project_and_receipt_clears_gap(self):
        self.invoke()
        self.invoke(dict(self.payload, hook_event_name='Stop', event_id='stop'))
        self.assertEqual(hook.drain_queue(self.vault, self.state)['processed'], 2)
        gaps = json.loads((self.state / 'receipt-gaps.json').read_text(encoding='utf-8'))['checkpoints']
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]['project'], self.project.name)
        engine = SyncEngine(self.vault, self.state)
        engine.note_create('notes/result.md', 'Synthetic result.', {'id': 'result', 'project': 'demo', 'type': 'semantic'})
        engine.receipt('finished', 'Synthetic result.', ['notes/result.md'], 'codex', session=gaps[0]['session'])
        engine.sync()
        self.assertEqual(json.loads((self.state / 'receipt-gaps.json').read_text(encoding='utf-8'))['potential_missing_receipts'], 0)

    def test_legacy_checkpoint_schema_migrates_without_losing_rows(self):
        engine = SyncEngine(self.vault, self.state)
        with engine.store._connect() as db:
            db.execute('DROP TABLE IF EXISTS receipt_checkpoints')
            db.execute('CREATE TABLE receipt_checkpoints(harness TEXT,session TEXT,at REAL,PRIMARY KEY(harness,session))')
            db.execute("INSERT INTO receipt_checkpoints VALUES ('codex','old',123)")
        hook.drain_queue(self.vault, self.state)
        gaps = json.loads((self.state / 'receipt-gaps.json').read_text(encoding='utf-8'))['checkpoints']
        self.assertEqual(gaps[0]['session'], 'old')

    def test_installed_zip_config_executes_from_external_project_without_global_writes(self):
        package = self.root / 'candidate.zip'
        def run(*args):
            result = subprocess.run([sys.executable, *map(str, args)], capture_output=True, text=True,
                                    encoding='utf-8', env=self.env, cwd=self.project, timeout=40)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result
        run(ROOT / 'scripts/build_v3_release.py', '--version', '3.1.1', '--output', package)
        with zipfile.ZipFile(package) as archive: archive.extractall(self.root / 'package')
        run(self.root / 'package/scripts/install_v3.py', '--vault', self.vault, '--state', self.state)
        installed = self.vault / '.claude/scripts/beyin_v3_bridge.py'
        self.assertTrue(installed.is_file())
        for harness in ('codex', 'claude'):
            config = self.invoke(extra=['--print-config'], harness=harness, script=installed)
            self.assertEqual(set(config['hooks']), set(bridge.EVENTS))
            command = config['hooks']['SessionStart'][0]['hooks'][0]['command']
            result = subprocess.run(command, shell=True, input=json.dumps(self.payload), capture_output=True,
                                    text=True, encoding='utf-8', env=self.env, cwd=self.project, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Receipt session=', json.loads(result.stdout)['hookSpecificOutput']['additionalContext'])
        self.assertFalse((self.home / '.codex/hooks.json').exists())
        self.assertFalse((self.home / '.claude/settings.json').exists())


if __name__ == '__main__':
    unittest.main()
