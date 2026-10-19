#!/usr/bin/env python3
"""Unit tests for beyin_v3_sizes.py: the read-only vault size inventory.

The module survives AutoDream's removal as an independent measurement helper:
doctor uses it for the single `oversize` field, nothing rewrites files.
"""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location('beyin_v3_sizes',
                                               ROOT / 'template/.claude/scripts/beyin_v3_sizes.py')
sizes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sizes)


class SizesInventoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-sizes-test-')
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name)

    def note(self, relative, chars):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# N\n' + 'x' * chars, encoding='utf-8')

    def test_small_vault_reports_counts_and_no_oversize(self):
        self.note('knowledge/concepts/kucuk.md', 100)
        self.note('notes/diger.md', 50)
        report = sizes.inventory(self.vault)
        self.assertEqual(report['notes'], 2)
        self.assertEqual(report['oversize'], [])

    def test_oversize_note_is_listed_with_shared_cap(self):
        self.note('knowledge/concepts/buyuk.md', sizes.NOTE_CAP_CHARS + 500)
        self.note('notes/kucuk.md', 10)
        report = sizes.inventory(self.vault)
        entries = {entry['path']: entry for entry in report['oversize']}
        self.assertEqual(list(entries), ['knowledge/concepts/buyuk.md'])
        entry = entries['knowledge/concepts/buyuk.md']
        self.assertFalse(entry['generated'])
        self.assertEqual(entry['cap'], sizes.NOTE_CAP_CHARS)
        self.assertEqual(report['notes'], 2)

    def test_generated_files_are_flagged_and_measured_beyond_note_trees(self):
        self.note('knowledge/index.md', sizes.NOTE_CAP_CHARS + 1)      # SIZE_CHECKED
        self.note('daily/v3/2026-10-19.md', sizes.NOTE_CAP_CHARS + 1)  # GENERATED_GLOBS
        report = sizes.inventory(self.vault)
        entries = {entry['path']: entry for entry in report['oversize']}
        self.assertIn('knowledge/index.md', entries)
        self.assertIn('daily/v3/2026-10-19.md', entries)
        self.assertTrue(entries['knowledge/index.md']['generated'])
        self.assertTrue(entries['daily/v3/2026-10-19.md']['generated'])

    def test_per_file_cap_overrides_the_shared_cap_for_notes(self):
        self.note('notes/ozet.md', sizes.NOTE_CAP_CHARS - 1)
        report = sizes.inventory(self.vault, limits={'notes/ozet.md': 2000})
        entries = {entry['path']: entry for entry in report['oversize']}
        self.assertIn('notes/ozet.md', entries)
        self.assertEqual(entries['notes/ozet.md']['cap'], 2000)

    def test_extra_and_missing_paths(self):
        # extra: handoff files outside the note trees share the note cap.
        self.note('🔮 850-Companion/Threads.md', sizes.NOTE_CAP_CHARS + 100)
        self.note('notes/normal.md', 10)
        report = sizes.inventory(self.vault, extra=('🔮 850-Companion/Threads.md',
                                                    'yok-olmayan/dosya.md'))
        paths = {entry['path'] for entry in report['oversize']}
        self.assertEqual(paths, {'🔮 850-Companion/Threads.md'})


if __name__ == '__main__':
    unittest.main()
