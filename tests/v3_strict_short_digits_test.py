#!/usr/bin/env python3
"""#358: Strict context must drop non-topical short digits and single-char tokens."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "template/.claude/scripts"))
import beyin_v3  # noqa: E402


class StrictShortDigitsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="v3-strict-digits-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.vault = root / "vault"
        self.vault.mkdir()
        self.state = root / "state"
        self.state.mkdir()
        self.store = beyin_v3.MemoryStore(self.state, self.vault)
        self.addCleanup(self.store.close)

        # Ingest a note that contains ubiquitous numbers 1, 2, 3, 42
        self.ingest(
            "general-note",
            "Sürüm 1.2.3 yayınlandı. Adım 1: ayarları yap. Adım 2: testi çalıştır. Madde 42 geçerli.",
            "knowledge/general.md",
            title="Genel Not"
        )
        # Ingest note with 3-digit number 200
        self.ingest(
            "cycle-note",
            "Cycle 200 delik mekanizması ve tork hesaplamaları.",
            "knowledge/cycle.md",
            title="Cycle 200 Mekanizması"
        )
        # Ingest note with hex identifier
        self.ingest(
            "hex-note",
            "722b4dd yayını ve paketleme detayları.",
            "knowledge/release.md",
            title="722b4dd Yayını"
        )
        # Ingest note with 4-digit year 2026
        self.ingest(
            "goals-note",
            "2026 yılı hedefleri ve bütçe planlaması.",
            "knowledge/goals.md",
            title="2026 Hedefleri"
        )

    def ingest(self, ident, text, source, title=""):
        path = self.vault / source
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        record = {
            "id": ident,
            "kind": "note",
            "status": "active",
            "visibility": "internal",
            "text": text,
            "facts": {},
            "source": source,
            "title": title,
            "updated_at": "2026-10-14T10:00:00Z"
        }
        self.store.ingest(record)

    def ids(self, query, passages=False, strict=True):
        if passages:
            res = self.store.context_for("claude", query, strict=strict)
        else:
            res = self.store.retrieve(query, strict=strict)
        return [r["id"] for r in res.get("records", [])]

    def test_short_digit_replies_abstain_in_both_strict_paths(self):
        """Short numerical answers ('1-2-3', '1 2', '2.', '42') must not pull unrelated notes (#358)."""
        noisy_queries = ["1-2-3", "1 2 3", "1 2", "2.", "1", "42", "99"]
        for query in noisy_queries:
            for passage_mode in (False, True):
                with self.subTest(query=query, passages=passage_mode):
                    res = self.ids(query, passages=passage_mode, strict=True)
                    self.assertEqual(res, [], f"Expected empty result for query '{query}' (passages={passage_mode})")

    def test_three_digit_and_year_queries_survive(self):
        """Numbers >= 3 digits (like '200' and '2026') carry topical significance and are preserved."""
        for passage_mode in (False, True):
            with self.subTest(passages=passage_mode):
                cycle_res = self.ids("Cycle 200 delik", passages=passage_mode, strict=True)
                self.assertEqual(cycle_res, ["cycle-note"])

                goals_res = self.ids("2026 hedefleri", passages=passage_mode, strict=True)
                self.assertEqual(goals_res, ["goals-note"])

    def test_alphanumeric_identifiers_survive(self):
        """Alphanumeric hashes like '722b4dd' are not pure digits and are preserved (#358)."""
        for passage_mode in (False, True):
            with self.subTest(passages=passage_mode):
                res = self.ids("722b4dd yayını", passages=passage_mode, strict=True)
                self.assertEqual(res, ["hex-note"])

    def test_candidates_in_strict_mode_abstains_on_short_digits(self):
        """Candidates retrieval with strict=True returns empty list on digit-only queries."""
        cands = self.store.candidates("1 2 3", strict=True)
        self.assertEqual(cands, [])

    def test_non_strict_retrieval_still_permits_numeric_queries(self):
        """Non-strict retrieval (strict=False) leaves terms intact for intentional search."""
        res = self.store.retrieve("1 2 3", strict=False)
        self.assertIn("general-note", [r["id"] for r in res.get("records", [])])

    def test_mixed_query_drops_only_short_digits(self):
        """In 'seçenek 1', '1' is dropped, leaving 'seçenek' without false positive digit matches."""
        # Query with non-matching word + matching digit: should not match general-note
        res = self.ids("seçenek 1", strict=True)
        self.assertNotIn("general-note", res)


if __name__ == "__main__":
    unittest.main()
