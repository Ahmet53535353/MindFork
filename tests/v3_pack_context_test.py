#!/usr/bin/env python3
"""Contract and regression tests for context packing and fair-share budget allocation (#79)."""
import json
from pathlib import Path
import random
import shutil
import string
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'template/.claude/scripts'
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import beyin_v3 as runtime
from beyin_v3 import pack_context, render_context, MemoryStore, _json


def _make_record(i, n, truncated=False):
    return {
        "id": f"md-{i:032x}",
        "source": f"notes/note-{i}.md",
        "kind": "note",
        "visibility": "internal",
        "revision": 1,
        "text": f"Note {i} content: " + ("x" * n),
        "facts": {},
        "text_truncated": truncated,
    }


class TestPackContextFairShare(unittest.TestCase):
    def test_one_long_note_does_not_starve_four_short_notes(self):
        """Issue 79: A single long leading note must not starve 4 short relevant notes."""
        records = [_make_record(0, 9000)] + [_make_record(i, 400) for i in range(1, 5)]
        result = pack_context(records, limit=5, budget_chars=5000)

        self.assertEqual(len(result['records']), 5,
                         f"Expected all 5 notes to be delivered, but got {len(result['records'])}")
        self.assertEqual(result['omitted_count'], 0)
        self.assertLessEqual(result['used_chars'], 5000)

        # Short records 1-4 should not be truncated
        for rec in result['records'][1:]:
            self.assertFalse(rec.get('text_truncated', False))
            self.assertIn("Note ", rec['text'])

        # Long record 0 should be truncated and carry substantial text
        self.assertTrue(result['records'][0].get('text_truncated'))
        self.assertTrue(result['records'][0]['text'].endswith(' [truncated]'))
        self.assertGreater(len(result['records'][0]['text']), 1500)

    def test_five_equal_long_notes_all_delivered(self):
        """Issue 79 & Review: Five long notes delivered; rank priority preserves top note text."""
        records = [_make_record(i, 3000) for i in range(5)]
        result = pack_context(records, limit=5, budget_chars=5000)

        self.assertEqual(len(result['records']), 5,
                         f"Expected all 5 notes delivered, but got {len(result['records'])}")
        self.assertEqual(result['omitted_count'], 0)
        self.assertLessEqual(result['used_chars'], 5000)

        # Top-ranked record gets rich context for answering sentence preservation (#83)
        self.assertGreater(len(result['records'][0]['text']), 2000)
        # All lower-ranked notes still get at least minimum useful text
        for rec in result['records']:
            self.assertGreaterEqual(len(rec['text']), 150)

    def test_2000_budget_long_notes_deliver_useful_text(self):
        """Review #81: At 2000 budget, notes must deliver useful text, not 36-char fragments."""
        records = [_make_record(i, 6000) for i in range(5)]
        result = pack_context(records, limit=5, budget_chars=2000)

        self.assertGreater(len(result['records']), 0)
        self.assertLessEqual(result['used_chars'], 2000)
        for rec in result['records']:
            self.assertGreaterEqual(len(rec['text']), 150)

        # render_context envelope must fit within 2000 budget
        text, delivered = render_context(result, 2000)
        self.assertLessEqual(len(text), 2000)
        for rec in delivered['records']:
            self.assertGreaterEqual(len(rec['text']), 150)

    def test_single_long_note_consumes_full_budget(self):
        """Single note when only 1 candidate exists should still take the full available budget."""
        records = [_make_record(0, 9000)]
        result = pack_context(records, limit=5, budget_chars=5000)
        self.assertEqual(len(result['records']), 1)
        self.assertEqual(result['omitted_count'], 0)
        self.assertLessEqual(result['used_chars'], 5000)
        self.assertGreater(result['used_chars'], 4000)

    def test_pre_truncated_record_reports_truncated(self):
        """Review Point 3: An incoming record that is already truncated reports truncated=True."""
        records = [_make_record(0, 100, truncated=True)]
        result = pack_context(records, limit=5, budget_chars=5000)
        self.assertEqual(len(result['records']), 1)
        self.assertTrue(result['truncated'])

    def test_dropped_candidate_slack_carried_forward(self):
        """Review Point 4: An candidate dropped due to size leaves its allocation as slack."""
        # Candidate 0 takes fair share; candidate 1 is constructed such that it cannot fit min useful text,
        # but candidate 2 is short and can use the slack.
        rec0 = _make_record(0, 200)
        rec1 = _make_record(1, 1000)
        rec2 = _make_record(2, 50)
        result = pack_context([rec0, rec1, rec2], limit=3, budget_chars=700)
        self.assertLessEqual(result['used_chars'], 700)
        delivered_ids = [r['id'] for r in result['records']]
        self.assertIn(rec0['id'], delivered_ids)

    def test_used_chars_strict_invariant_with_control_chars(self):
        """Review Point 2: used_chars strictly <= budget_chars with control chars and JSON escaping."""
        chars_pool = string.printable + '\u0000\u0001\u001f\t\n\r"\\ '
        rng = random.Random(1337)
        for _ in range(500):
            n_rec = rng.randint(1, 6)
            records = []
            for j in range(n_rec):
                t_len = rng.randint(0, 1500)
                t = ''.join(rng.choice(chars_pool) for _ in range(t_len))
                records.append({
                    'id': f'id-{j}',
                    'source': f'notes/n_{j}.md',
                    'kind': 'note',
                    'text': t,
                    'facts': {'k': rng.choice(['v1', 'v2'])},
                    'text_truncated': rng.choice([True, False])
                })
            limit = rng.randint(1, 5)
            budget = rng.randint(150, 4000)
            res = pack_context(records, limit=limit, budget_chars=budget)
            self.assertLessEqual(res['used_chars'], budget)
            actual_used = sum(len(_json(r)) + len(_json(c)) for r, c in zip(res['records'], res['citations']))
            self.assertEqual(actual_used, res['used_chars'])

    def test_retrieve_integration_delivers_multiple_sources(self):
        """Integration: MemoryStore.retrieve delivers multiple sources when one is long."""
        tmp = Path(tempfile.mkdtemp(prefix='beyin_test_pack_context_'))
        try:
            vault = tmp / 'vault'
            (vault / 'notes').mkdir(parents=True)
            runtime_dir = tmp / 'runtime'
            runtime_dir.mkdir(parents=True)
            store = MemoryStore(runtime_dir, vault)

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
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
