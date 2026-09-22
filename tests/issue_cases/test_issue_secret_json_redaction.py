"""Reproduction tests for secret filter JSON/quoted key-value redaction."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))

from beyin_v3_secrets import redact
from beyin_v3_jev import _safe
from beyin_v3 import MemoryStore
from beyin_v3_preferences import save
from beyin_v3_sync import SyncEngine


class TestSecretJsonRedaction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.vault = root / 'vault'
        self.vault.mkdir()
        self.state = root / 'state'
        self.state.mkdir()
        self.store = MemoryStore(self.state, self.vault)

    def test_quoted_json_secrets_are_redacted(self):
        """JSON-formatted credentials like {"api_key": "secret"} must be detected and redacted."""
        fixtures = [
            ('{"api_key": "synthetic_key_123456"}', 'synthetic_key_123456'),
            ('{"access_token": "synthetic_token_123"}', 'synthetic_token_123'),
            ('{"token": "synthetic_token_val_123"}', 'synthetic_token_val_123'),
            ('{"secret": "synthetic_secret_val_123"}', 'synthetic_secret_val_123'),
            ('{"password": "synthetic_password_123"}', 'synthetic_password_123'),
            ('{"passwd": "synthetic_passwd_val_123"}', 'synthetic_passwd_val_123'),
        ]
        for text, secret in fixtures:
            with self.subTest(text=text):
                filtered, count = redact(text, self.state)
                self.assertGreaterEqual(count, 1, f"Failed to detect secret in: {text}")
                self.assertNotIn(secret, filtered)
                self.assertIn('[REDACTED]', filtered)

    def test_single_quoted_and_mixed_secrets_are_redacted(self):
        """Single-quoted or mixed-quote formats must be detected and redacted."""
        fixtures = [
            ("{'api_key': 'synthetic_key_123456'}", 'synthetic_key_123456'),
            ("{'password': 'synthetic_password_123'}", 'synthetic_password_123'),
            ('api_key: "synthetic_key_123456"', 'synthetic_key_123456'),
            ("api_key: 'synthetic_key_123456'", 'synthetic_key_123456'),
        ]
        for text, secret in fixtures:
            with self.subTest(text=text):
                filtered, count = redact(text, self.state)
                self.assertGreaterEqual(count, 1, f"Failed to detect secret in: {text}")
                self.assertNotIn(secret, filtered)

    def test_url_query_parameter_delimiter(self):
        """URL query parameter secret redaction must stop at & delimiter."""
        url = "https://api.example.com/v1?api_key=synthetic_secret_token_123&format=json"
        filtered, count = redact(url, self.state)
        self.assertGreaterEqual(count, 1)
        self.assertNotIn("synthetic_secret_token_123", filtered)
        self.assertIn("&format=json", filtered)

    def test_jev_safe_blocks_cards_with_json_secrets(self):
        """Jev _safe must raise ValueError('advisor_sensitive_input') when card payload contains JSON secrets."""
        card_with_secret = [
            "search query",
            [
                {
                    "id": "card-1",
                    "title": "Secret Note",
                    "statement": json.dumps({"text": 'config: {"api_key": "synthetic_key_123456"}'}),
                    "scope": "project:test",
                    "domains": ["note"],
                }
            ],
        ]
        with self.assertRaises(ValueError) as cm:
            _safe(self.store, card_with_secret)
        self.assertEqual(str(cm.exception), 'advisor_sensitive_input')

    def test_sync_engine_note_create_redacts_json_secrets(self):
        """SyncEngine note_create must redact JSON-formatted credentials when secret_filter is enabled."""
        save(self.vault, {'secret_filter': True})
        engine = SyncEngine(self.vault, self.state)
        note_body = 'Service credentials:\n{"api_key": "synthetic_key_123456", "active": true}\n'
        res = engine.note_create('notes/credentials.md', note_body)
        self.assertGreaterEqual(res['secrets_redacted'], 1)
        content = (self.vault / 'notes/credentials.md').read_text(encoding='utf-8')
        self.assertNotIn('synthetic_key_123456', content)
        self.assertIn('[REDACTED]', content)


if __name__ == '__main__':
    unittest.main()
