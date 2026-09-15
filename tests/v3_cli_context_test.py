"""Context must refresh source state without lifecycle hooks."""
import json
from pathlib import Path
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

    def test_context_refuses_degraded_sync_without_stale_result(self):
        self.source.write_text('---\nunsupported:\n  nested: metadata\n---\nChanged source',encoding='utf-8')
        result=self.run_cli('context','synthetic calibration')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stdout,'')
        self.assertIn('sync',result.stderr.lower())
        self.assertIn('degraded',result.stderr.lower())

    def test_context_refuses_conflict_without_stale_result(self):
        (self.vault/'notes/duplicate.md').write_bytes(self.source.read_bytes())
        result=self.run_cli('context','synthetic calibration')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(result.stdout,'')
        self.assertIn('conflict',result.stderr.lower())

if __name__=='__main__':unittest.main()
