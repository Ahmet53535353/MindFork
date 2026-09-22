import unittest
import sys
import tempfile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "template/.claude/scripts"))

from beyin_v3_sync import SyncEngine
from beyin_v3 import ReceiptConflict


class TestIssueReceiptStateReset(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.vault = Path(self.tmp) / "vault"
        self.vault.mkdir()
        (self.vault / "notes").mkdir()
        (self.vault / "notes/task.md").write_text("# Task\nInitial work item.\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_receipt_submission_after_state_reset_does_not_deadlock(self):
        """State reset or multi-device vault sync must not cause receipt projection deadlock."""
        state1 = Path(self.tmp) / "state1"
        engine1 = SyncEngine(self.vault, state1)
        engine1.sync()
        engine1.receipt("event-1", "Initial calibration completed.", ["notes/task.md"], "codex", session="s1")

        outcomes1 = (self.vault / "knowledge/v3/outcomes.md").read_text(encoding="utf-8")
        self.assertIn("Initial calibration completed.", outcomes1)

        # Simulate state reset (wiped cache, new machine, Obsidian Sync)
        state2 = Path(self.tmp) / "state2"
        engine2 = SyncEngine(self.vault, state2)
        engine2.sync()

        # In unpatched versions, this fails with ReceiptConflict: receipt projection conflict
        res = engine2.receipt("event-2", "Second phase verified.", ["notes/task.md"], "codex", session="s2")
        self.assertEqual(res["status"], "succeeded")

        outcomes2 = (self.vault / "knowledge/v3/outcomes.md").read_text(encoding="utf-8")
        self.assertIn("Initial calibration completed.", outcomes2)
        self.assertIn("Second phase verified.", outcomes2)

    def test_existing_receipt_reassertion_after_state_reset(self):
        """Calling receipt() on an existing receipt after state reset must not trigger false source change conflict."""
        state1 = Path(self.tmp) / "state1"
        engine1 = SyncEngine(self.vault, state1)
        engine1.sync()
        engine1.receipt("event-1", "Initial calibration completed.", ["notes/task.md"], "codex", session="s1")

        # State reset with prior sync
        state2 = Path(self.tmp) / "state2"
        engine2 = SyncEngine(self.vault, state2)
        engine2.sync()

        # In unpatched versions, re-submitting event-1 raises ReceiptConflict: receipt source manually changed
        res = engine2.receipt("event-1", "Initial calibration completed.", ["notes/task.md"], "codex", session="s1")
        self.assertEqual(res["status"], "succeeded")

    def test_direct_receipt_call_without_prior_sync_recovers_receipt(self):
        """Calling receipt() before sync() on fresh state must recover on-disk receipt without conflict."""
        state1 = Path(self.tmp) / "state1"
        engine1 = SyncEngine(self.vault, state1)
        engine1.sync()
        engine1.receipt("event-1", "Initial calibration completed.", ["notes/task.md"], "codex", session="s1")

        # Fresh state without calling sync() first
        state3 = Path(self.tmp) / "state3"
        engine3 = SyncEngine(self.vault, state3)
        res = engine3.receipt("event-1", "Initial calibration completed.", ["notes/task.md"], "codex", session="s1")
        self.assertEqual(res["status"], "succeeded")

    def test_manual_receipt_tampering_still_fails(self):
        """Genuine manual tampering with receipt content must still raise ReceiptConflict."""
        state1 = Path(self.tmp) / "state1"
        engine1 = SyncEngine(self.vault, state1)
        engine1.sync()
        res1 = engine1.receipt("event-1", "Original text.", ["notes/task.md"], "codex", session="s1")

        # Tamper with the receipt file
        receipt_file = self.vault / res1["source"]
        receipt_file.write_text(receipt_file.read_text(encoding="utf-8").replace("Original text.", "Tampered text."), encoding="utf-8")

        state2 = Path(self.tmp) / "state2"
        engine2 = SyncEngine(self.vault, state2)
        with self.assertRaises(ReceiptConflict):
            engine2.receipt("event-1", "Original text.", ["notes/task.md"], "codex", session="s1")


if __name__ == "__main__":
    unittest.main()
