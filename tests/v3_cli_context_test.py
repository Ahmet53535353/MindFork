"""Context must refresh source state without lifecycle hooks."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class ContextRefreshTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name)/'vault'
        (self.vault/'notes').mkdir(parents=True)
        self.state = Path(self.temp.name)/'state'
        self.source = self.vault/'notes/decision.md'
        self.write('Initial synthetic calibration value.')
        result = self.run_cli('sync')
        self.assertEqual(result.returncode, 0, result.stderr)

    def write(self, body):
        self.source.write_text('---\n{"id":"calibration","kind":"fact","project":"demo","visibility":"internal"}\n---\n'+body+'\n',encoding='utf-8')

    def run_cli(self, *args):
        return subprocess.run([sys.executable,str(ROOT/'scripts/beyin_v3.py'),'--vault',str(self.vault),'--state',str(self.state),*args],capture_output=True,text=True,encoding='utf-8')

    def test_context_refreshes_external_edit_without_hook(self):
        self.write('Current synthetic calibration value CHANGED.')
        result = self.run_cli('context','synthetic calibration','--project','demo')
        self.assertEqual(result.returncode,0,result.stderr)
        output=json.loads(result.stdout)
        self.assertIn('CHANGED',output['records'][0]['text'])
        self.assertNotIn('Initial',result.stdout)

    def test_no_sync_source_cli_does_not_create_bytecode(self):
        from v3_package_helpers import snapshot
        checkout = Path(self.temp.name) / 'read-only checkout'
        for name in ('scripts/beyin_v3.py', 'template/.claude/scripts/beyin_v3.py'):
            target = checkout / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, target)
        before = snapshot(checkout), snapshot(self.vault), snapshot(self.state)
        env = dict(os.environ)
        env.pop('PYTHONDONTWRITEBYTECODE', None)
        env.pop('PYTHONPYCACHEPREFIX', None)
        result = subprocess.run(
            [sys.executable, str(checkout / 'scripts/beyin_v3.py'),
             '--vault', str(self.vault), '--state', str(self.state),
             'context', 'synthetic calibration', '--no-sync'],
            env=env, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([r['id'] for r in json.loads(result.stdout)['records']], ['calibration'])
        self.assertEqual((snapshot(checkout), snapshot(self.vault), snapshot(self.state)), before)

    def test_no_sync_missing_runtime_and_jev_rejection_do_not_write(self):
        from v3_package_helpers import snapshot
        missing = Path(self.temp.name) / 'missing runtime'
        for extra in ([], ['--jev']):
            with self.subTest(extra=extra):
                before = snapshot(self.vault)
                result = subprocess.run(
                    [sys.executable, str(ROOT / 'scripts/beyin_v3.py'),
                     '--vault', str(self.vault), '--state', str(missing),
                     'context', 'synthetic calibration', '--no-sync', *extra],
                    capture_output=True, text=True, encoding='utf-8')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')
                self.assertIn('cannot be combined' if extra else 'not initialized', result.stderr)
                self.assertFalse(missing.exists())
                self.assertEqual(snapshot(self.vault), before)

    def test_context_serves_fresh_healthy_subset_with_explicit_degraded_warning(self):
        healthy = self.vault/'notes/healthy.md'
        healthy.write_text('Current healthy nebula calibration note.\n', encoding='utf-8')
        self.source.write_text('---\nunsupported:\n  nested: metadata\n---\nChanged source',encoding='utf-8')
        result=self.run_cli('context','nebula calibration')
        self.assertEqual(result.returncode,0,result.stderr)
        output=json.loads(result.stdout)
        self.assertTrue(output['partial'])
        self.assertEqual(output['source_sync']['status'],'degraded')
        self.assertEqual(output['source_sync']['warning_count'],1)
        self.assertEqual(
            Path(output['source_sync']['warnings'][0]['source']).parts,
            ('notes', 'decision.md'),
        )
        self.assertIn('healthy.md',{record['source'].split('/')[-1] for record in output['records']})
        self.assertNotIn('Initial',result.stdout)

    def test_context_refuses_conflict_without_stale_result(self):
        (self.vault/'notes/duplicate.md').write_bytes(self.source.read_bytes())
        result=self.run_cli('context','synthetic calibration')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stdout,'')
        self.assertIn('conflict',result.stderr.lower())

if __name__=='__main__':unittest.main()
