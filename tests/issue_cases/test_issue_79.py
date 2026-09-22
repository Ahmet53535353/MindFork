import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
import sys
SCRIPTS = ROOT / 'template/.claude/scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from beyin_v3 import pack_context, MemoryStore


def _make_record(i, n):
    return {
        "id": f"md-{i:032x}",
        "source": f"notes/note-{i}.md",
        "kind": "note",
        "visibility": "internal",
        "revision": 1,
        "text": f"Note {i} content: " + ("x" * n),
        "facts": {},
    }


class TestIssue79PackContextFairShare(unittest.TestCase):
    def test_one_long_note_does_not_starve_four_short_notes(self):
        """Issue 79: A single long leading note must not starve 4 short relevant notes."""
        records = [_make_record(0, 9000)] + [_make_record(i, 400) for i in range(1, 5)]
        result = pack_context(records, limit=5, budget_chars=5000)

        # On unpatched code, result['records'] is 1 and omitted_count is 4.
        self.assertEqual(len(result['records']), 5,
                         f"Expected all 5 notes to be delivered, but got {len(result['records'])}")
        self.assertEqual(result['omitted_count'], 0)
        self.assertLessEqual(result['used_chars'], 5000)

        # Short records 1-4 should not be truncated
        for rec in result['records'][1:]:
            self.assertFalse(rec.get('text_truncated', False))
            self.assertIn("Note ", rec['text'])

        # Long record 0 should be truncated
        self.assertTrue(result['records'][0].get('text_truncated'))
        self.assertTrue(result['records'][0]['text'].endswith(' [truncated]'))

    def test_five_equal_long_notes_all_delivered(self):
        """Issue 79: Five equal long notes should all be delivered within fair shares."""
        records = [_make_record(i, 3000) for i in range(5)]
        result = pack_context(records, limit=5, budget_chars=5000)

        # On unpatched code, only 2 notes are delivered and 3 are omitted.
        self.assertEqual(len(result['records']), 5,
                         f"Expected all 5 notes delivered, but got {len(result['records'])}")
        self.assertEqual(result['omitted_count'], 0)
        self.assertLessEqual(result['used_chars'], 5000)

    def test_single_long_note_consumes_full_budget(self):
        """Single note when only 1 candidate exists should still take the full available budget."""
        records = [_make_record(0, 9000)]
        result = pack_context(records, limit=5, budget_chars=5000)
        self.assertEqual(len(result['records']), 1)
        self.assertEqual(result['omitted_count'], 0)
        self.assertLessEqual(result['used_chars'], 5000)
        self.assertGreater(result['used_chars'], 4000)

    def test_retrieve_integration_delivers_multiple_sources(self):
        """Integration: MemoryStore.retrieve delivers multiple sources when one is long."""
        tmp = Path(tempfile.mkdtemp(prefix='beyin_test_issue79_'))
        try:
            vault = tmp / 'vault'
            (vault / 'notes').mkdir(parents=True)
            runtime = tmp / 'runtime'
            runtime.mkdir(parents=True)
            store = MemoryStore(runtime, vault)

            # Ingest 1 long note and 3 short notes with shared query topic 'architecture'
            (vault / "notes/arch-overview.md").write_text("System architecture overview documentation " + ("detailed specs " * 400), encoding='utf-8')
            store.ingest({
                "id": "arch-overview",
                "source": "notes/arch-overview.md",
                "kind": "note",
                "visibility": "internal",
                "revision": 1,
                "text": "System architecture overview documentation " + ("detailed specs " * 400),
                "facts": {},
            })
            for i in range(1, 4):
                path = f"notes/arch-component-{i}.md"
                text = f"Architecture component {i} short summary and configuration."
                (vault / path).write_text(text, encoding='utf-8')
                store.ingest({
                    "id": f"arch-component-{i}",
                    "source": path,
                    "kind": "note",
                    "visibility": "internal",
                    "revision": 1,
                    "text": text,
                    "facts": {},
                })

            res = store.retrieve("architecture", limit=4, budget_chars=4000)
            self.assertEqual(len(res['records']), 4,
                             f"Store.retrieve should deliver 4 notes, but got {len(res['records'])}")
            self.assertEqual(res['omitted_count'], 0)
            self.assertLessEqual(res['used_chars'], 4000)
            store.close()
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
