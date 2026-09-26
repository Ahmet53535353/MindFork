"""AutoDream konsolidasyon penceresi — faz 1 (kapılar + salt-okunur ölçüm).

Spec: docs/specs/2026-09-26-autodream-lite-roadmap.md (§0 kapılar, §1 boyut, §3 ısı, §5.1)
"""
import datetime as dt
import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'template/.claude/scripts'
CLI = ROOT / 'scripts/beyin_v3.py'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


def load_engine():
    spec = importlib.util.spec_from_file_location('dream_engine', SCRIPTS / 'beyin_v3.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def iso(delta_days, base=None):
    moment = (base or dt.datetime.now(dt.timezone.utc)) + dt.timedelta(days=delta_days)
    return moment.isoformat()


class DreamTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = load_engine()
        cls.dream = load('dream_subject', 'beyin_v3_dream.py')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-dream-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.state = self.root / 'state'
        self.store = self.engine.MemoryStore(self.state, self.vault)

    # -- fixtures -------------------------------------------------------
    def seed(self, records=(), receipts=(), meta=None):
        db = sqlite3.connect(self.state / 'memory.sqlite3')
        try:
            for record in records:
                db.execute('INSERT OR REPLACE INTO records VALUES (?,?)',
                           (record['id'], json.dumps(record)))
            for receipt in receipts:
                db.execute('INSERT OR REPLACE INTO receipts VALUES (?,?)',
                           (receipt['id'], receipt['payload']))
            for key, value in (meta or {}).items():
                db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, value))
            db.commit()
        finally:
            db.close()

    def receipt(self, event_id, refs, when=None):
        return {'id': event_id, 'payload': json.dumps(
            {'event_id': event_id, 'summary': 's', 'refs': list(refs), 'harness': 'codex',
             'created_at': when or iso(0)})}

    def note(self, source, **overrides):
        # Synced records carry no derived title: the heading lives in the body, exactly
        # like a real vault. Only an explicit frontmatter title sets the record title.
        record = {'id': source.replace('/', '-').replace('.md', ''), 'source': source,
                  'text': '# ' + source.rsplit('/', 1)[-1][:-3] + '\n',
                  'kind': 'note', 'status': 'active', 'visibility': 'internal', 'revision': 1}
        record.update(overrides)
        return record

    def write_source(self, relative, text):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def report(self, **kwargs):
        return self.dream.report(self.vault, self.state, self.store, **kwargs)

    # -- gates ----------------------------------------------------------
    def test_first_run_passes_every_gate(self):
        result = self.report()
        self.assertTrue(result['gates']['passed'], result['gates'])
        self.assertEqual(result['gates']['blocked_by'], [])
        self.assertIsNone(result['gates']['last_run'])

    def test_gate_rejects_a_run_inside_the_day(self):
        self.seed(meta={'dream.last_run': iso(0)})
        result = self.report()
        self.assertFalse(result['gates']['passed'])
        self.assertIn('min_hours', result['gates']['blocked_by'])

    def test_gate_rejects_a_window_without_new_receipts(self):
        self.seed(meta={'dream.last_run': iso(-3)}, receipts=[self.receipt('r1', ['knowledge/a.md'], iso(-4))])
        result = self.report()
        self.assertFalse(result['gates']['passed'])
        self.assertIn('min_receipts', result['gates']['blocked_by'])
        self.assertEqual(result['gates']['new_receipts'], 0)

    def test_gate_counts_only_receipts_after_the_last_run(self):
        self.seed(meta={'dream.last_run': iso(-2)},
                  receipts=[self.receipt('old', ['knowledge/a.md'], iso(-5)),
                            self.receipt('r1', ['knowledge/a.md'], iso(-1)),
                            self.receipt('r2', ['knowledge/b.md'], iso(-1)),
                            self.receipt('r3', ['knowledge/b.md'], iso(0)),
                            self.receipt('r4', ['knowledge/c.md'], iso(0)),
                            self.receipt('r5', ['knowledge/c.md'], iso(0))])
        gates = self.report()['gates']
        self.assertTrue(gates['passed'], gates)
        self.assertEqual(gates['new_receipts'], 5)
        self.assertGreaterEqual(gates['hours_since'], 48)

    def test_locked_state_reports_a_closed_gate(self):
        handle = open(self.state / 'dream.lock', 'a+b')
        sys.path.insert(0, str(SCRIPTS))
        try:
            import _portalock
            with _portalock.exclusive(handle):
                gates = self.report()['gates']
        finally:
            sys.path.remove(str(SCRIPTS))
            handle.close()
        self.assertTrue(gates['locked'])
        self.assertFalse(gates['passed'])
        self.assertIn('lock', gates['blocked_by'])

    def test_gate_never_writes(self):
        watermark = iso(0)
        self.seed(meta={'dream.last_run': watermark})
        self.report()
        db = sqlite3.connect(self.state / 'memory.sqlite3')
        try:
            row = db.execute("SELECT value FROM metadata WHERE key='dream.last_run'").fetchone()
        finally:
            db.close()
        self.assertEqual(row[0], watermark)
        self.assertFalse((self.vault / 'archive').exists())

    # -- inventory ------------------------------------------------------
    def test_inventory_counts_notes_and_flags_oversize_files(self):
        self.write_source('knowledge/a.md', 'x' * 100)
        self.write_source('knowledge/index.md', 'i' * (12 * 1024 + 5))
        inventory = self.report()['inventory']
        self.assertEqual(inventory['notes'], 2)
        self.assertGreaterEqual(inventory['chars'], 12 * 1024)
        oversize = {entry['path']: entry for entry in inventory['oversize']}
        self.assertIn('knowledge/index.md', oversize)
        self.assertNotIn('knowledge/a.md', oversize)

    def test_generated_projections_are_reported_separately(self):
        self.write_source('knowledge/v3/outcomes.md', 'o' * (12 * 1024 + 1))
        paths = {entry['path'] for entry in self.report()['inventory']['oversize']}
        self.assertIn('knowledge/v3/outcomes.md', paths)

    # -- heat and candidates -------------------------------------------
    def test_heat_counts_receipt_citations_per_source(self):
        self.seed(receipts=[self.receipt('r1', ['knowledge/a.md']),
                            self.receipt('r2', ['knowledge/a.md']),
                            self.receipt('r3', ['knowledge/b.md', 'knowledge/a.md'])])
        self.assertEqual(self.report()['heat'], {'knowledge/a.md': 3, 'knowledge/b.md': 1})

    def test_prune_needs_draft_stale_and_uncited(self):
        self.seed(records=[self.note('knowledge/cold.md', status='draft', updated_at=iso(-120)),
                           self.note('knowledge/cited-draft.md', status='draft', updated_at=iso(-120)),
                           self.note('knowledge/fresh-draft.md', status='draft', updated_at=iso(-2)),
                           self.note('knowledge/active.md', updated_at=iso(-120))],
                  receipts=[self.receipt('r1', ['knowledge/cited-draft.md'], iso(-1))])
        prune = {entry['source'] for entry in self.report()['candidates']['prune']}
        self.assertEqual(prune, {'knowledge/cold.md'})

    def test_refresh_candidates_are_oversize_notes(self):
        self.write_source('knowledge/huge.md', 'h' * (12 * 1024 + 1))
        self.seed(records=[self.note('knowledge/huge.md'), self.note('knowledge/small.md')])
        refresh = {entry['path'] for entry in self.report()['candidates']['refresh']}
        self.assertEqual(refresh, {'knowledge/huge.md'})

    def test_merge_pairs_titles_that_differ_only_in_shape(self):
        self.seed(records=[self.note('knowledge/stripe-webhook.md', text='# Stripe Webhook\n'),
                           self.note('knowledge/stripe_webhook_race.md', text='# stripe_webhook: race\n'),
                           self.note('knowledge/billing.md', text='# Billing\n')],
                  receipts=[self.receipt('r1', ['knowledge/stripe-webhook.md']),
                            self.receipt('r2', ['knowledge/stripe_webhook_race.md']),
                            self.receipt('r3', ['knowledge/billing.md'])])
        pairs = self.report()['candidates']['merge']
        self.assertEqual(len(pairs), 1)
        self.assertEqual(sorted(pair for pair in pairs[0]['sources']),
                         ['knowledge/stripe-webhook.md', 'knowledge/stripe_webhook_race.md'])

    def test_merge_never_pairs_uncited_notes(self):
        self.seed(records=[self.note('knowledge/stripe-webhook.md', text='# Stripe Webhook\n'),
                           self.note('knowledge/stripe_webhook_race.md', text='# stripe_webhook: race\n')])
        self.assertEqual(self.report()['candidates']['merge'], [])

    def test_merge_falls_back_to_the_source_stem_without_a_heading(self):
        self.seed(records=[self.note('knowledge/stripe-webhook.md', text='duz metin, baslik yok\n'),
                           self.note('knowledge/stripe_webhook.md.copy', text='duz metin\n')],
                  receipts=[self.receipt('r1', ['knowledge/stripe-webhook.md']),
                            self.receipt('r2', ['knowledge/stripe_webhook.md.copy'])])
        pairs = self.report()['candidates']['merge']
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]['sources'], ['knowledge/stripe-webhook.md', 'knowledge/stripe_webhook.md.copy'])

    def test_dry_run_report_is_deterministic(self):
        self.seed(records=[self.note('knowledge/a.md')],
                  receipts=[self.receipt('r1', ['knowledge/a.md'])])
        self.assertEqual(json.dumps(self.report(), sort_keys=True),
                         json.dumps(self.report(), sort_keys=True))

    # -- cli ------------------------------------------------------------
    def test_cli_dream_is_read_only_and_reports_no_model_use(self):
        self.write_source('knowledge/a.md', 'x' * 100)
        self.seed(records=[self.note('knowledge/a.md')],
                  receipts=[self.receipt('r1', ['knowledge/a.md'])])
        before = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        result = subprocess.run([sys.executable, str(CLI), '--vault', str(self.vault),
                                 '--state', str(self.state), 'dream'],
                                capture_output=True, text=True, timeout=60,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload['model_calls'])
        self.assertFalse(payload['network'])
        self.assertIn('gates', payload)
        self.assertIn('inventory', payload)
        after = sorted(str(p.relative_to(self.root)) for p in self.root.rglob('*'))
        self.assertEqual(before, after)

    def test_cli_reports_gated_windows_without_failing(self):
        self.seed(meta={'dream.last_run': iso(0)})
        result = subprocess.run([sys.executable, str(CLI), '--vault', str(self.vault),
                                 '--state', str(self.state), 'dream'],
                                capture_output=True, text=True, timeout=60,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)['gates']['passed'])


if __name__ == '__main__':
    unittest.main()
