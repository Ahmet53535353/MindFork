#!/usr/bin/env python3
"""Recency tie-break over Obsidian frontmatter aliases, synthetic local fixtures only."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / 'template/.claude/scripts/beyin_v3_sync.py'


def load_module():
    if not MODULE.is_file():
        raise AssertionError('SyncEngine not implemented')
    spec = importlib.util.spec_from_file_location('beyin_v3_recency_test_subject', MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    scripts = str(MODULE.parent)
    sys.path.insert(0, scripts)
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old
        sys.path.remove(scripts)
    return module


BODY = 'Nebula calibration toplanti kararlari owner Synthetic Reviewer.\n'


class RecencyAliasTest(unittest.TestCase):
    def setUp(self):
        self.module = load_module()
        self.tmp = tempfile.TemporaryDirectory(prefix='beyin-recency-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'Synthetic Beyin Çalışma'
        self.vault.mkdir()
        self.state = self.root / 'runtime'
        self.engine = self.module.SyncEngine(self.vault, self.state)
        self.addCleanup(lambda: getattr(self.engine.store, 'close', lambda: None)())

    def write(self, name, frontmatter, body=BODY):
        path = self.vault / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('---\n' + frontmatter.strip() + '\n---\n' + body, encoding='utf-8')
        return path

    def indexed(self, id):
        return {record['id']: record for record in
                self.engine.store.retrieve('Nebula calibration toplanti kararlari',
                                           project='nebula')['records']}[id]

    def test_alias_dates_outrank_the_id_tie_break(self):
        # The ids sort opposite to the dates, so an empty recency key ranks the old note first.
        self.assertGreater('zzz-old-note', 'aaa-new-note')
        self.write('notes/old.md', 'id: zzz-old-note\nproject: nebula\nupdated: 2020-01-01')
        self.write('notes/new.md', 'id: aaa-new-note\nproject: nebula\nmodified: 2026-09-18')
        self.assertEqual(self.engine.sync()['status'], 'succeeded')
        ranked = self.engine.store.retrieve('Nebula calibration toplanti kararlari',
                                            project='nebula')['records']
        self.assertEqual([record['id'] for record in ranked], ['aaa-new-note', 'zzz-old-note'])
        self.assertEqual(ranked[0]['updated_at'], '2026-09-18')
        self.assertEqual(ranked[1]['updated_at'], '2020-01-01')

    def test_explicit_updated_at_wins_over_aliases(self):
        self.write('notes/explicit.md', 'id: explicit-note\nproject: nebula\n'
                                        'updated_at: 2026-01-02\nmodified: 2019-05-05\n'
                                        'updated: 2018-03-04')
        self.assertEqual(self.engine.sync()['status'], 'succeeded')
        self.assertEqual(self.indexed('explicit-note')['updated_at'], '2026-01-02')

    def test_alias_precedence_follows_the_declared_order(self):
        self.write('notes/order.md', 'id: order-note\nproject: nebula\n'
                                     'date_modified: 2011-01-01\nmodified: 2022-02-02\n'
                                     'last_modified: 2033-03-03')
        self.assertEqual(self.engine.sync()['status'], 'succeeded')
        self.assertEqual(self.indexed('order-note')['updated_at'], '2022-02-02')

    def test_non_iso_and_non_string_aliases_are_ignored(self):
        # The mini YAML parser hands back a bare year as an int, not a string.
        self.write('notes/prose.md', 'id: prose-note\nproject: nebula\n'
                                     'modified: 18 September 2026\nupdated: 2026')
        self.assertEqual(self.engine.sync()['status'], 'succeeded')
        record = self.indexed('prose-note')
        self.assertNotIn('updated_at', record)
        self.assertEqual(record['modified'], '18 September 2026')
        self.assertEqual(record['updated'], 2026)

    def test_sync_leaves_alias_sources_byte_identical(self):
        paths = [self.write('notes/old.md', 'id: zzz-old-note\nproject: nebula\nupdated: 2020-01-01'),
                 self.write('notes/new.md', 'id: aaa-new-note\nproject: nebula\nmodified: 2026-09-18')]
        before = [path.read_bytes() for path in paths]
        self.engine.sync()
        self.engine.sync()
        self.assertEqual([path.read_bytes() for path in paths], before)

    def test_task_update_round_trip_keeps_the_alias_out_of_frontmatter(self):
        path = self.write('tasks/nebula.md', 'id: nebula-task\nkind: task\nrevision: 1\n'
                                             'project: nebula\nstatus: active\nowner: Synthetic Reviewer\n'
                                             'modified: 2026-09-18')
        self.assertEqual(self.engine.sync()['status'], 'succeeded')
        self.assertEqual(self.indexed('nebula-task')['updated_at'], '2026-09-18')
        updated = self.engine.update_task('nebula-task', 1, {'status': 'waiting'})
        self.assertEqual(updated['status'], 'waiting')
        self.assertEqual(updated['updated_at'], '2026-09-18')
        metadata, body = self.module.parse(path.read_text(encoding='utf-8'))
        self.assertEqual(metadata['modified'], '2026-09-18')
        self.assertNotIn('updated_at', metadata)
        self.assertEqual(body, BODY)


if __name__ == '__main__':
    unittest.main()
