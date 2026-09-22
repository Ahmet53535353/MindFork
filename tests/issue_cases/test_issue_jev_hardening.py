import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))

import beyin_v3_jev_client as j


class TestIssueJevHardening(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.vault = Path(self.temp.name)
        self.cards = [dict(id='one', title='A', statement='B', scope='user', domains=['all'])]

    def config(self, **kw):
        (self.vault / 'jev.json').write_text(json.dumps(dict(mode='shadow', **kw)), encoding='utf-8')

    def test_endpoint_malformed_ports_raise_endpoint_invalid(self):
        """Malformed port numbers must be rejected with ValueError('endpoint_invalid')."""
        malformed_urls = [
            'https://api.typesafe.ai:99999',
            'https://api.typesafe.ai:notaport',
            'https://api.typesafe.ai:-1',
        ]
        for url in malformed_urls:
            with self.subTest(url=url):
                with self.assertRaises(ValueError) as cm:
                    j._endpoint(url)
                self.assertEqual(str(cm.exception), 'endpoint_invalid')

    def test_evaluate_with_malformed_port_returns_endpoint_invalid_diagnostic(self):
        """Evaluating with a malformed port in base_url must yield 'endpoint_invalid' diagnostic, not 'request_failed'."""
        self.config(base_url='https://api.typesafe.ai:99999')
        result = j.evaluate(self.vault, 'test query', self.cards)
        self.assertTrue(result['degraded'])
        self.assertIn('endpoint_invalid', result['diagnostics'])
        self.assertNotIn('request_failed', result['diagnostics'])

    def test_cache_hit_race_configuration_changed_not_swallowed(self):
        """If configuration changes during cache read, configuration_changed must not be swallowed into cache_unavailable."""
        self.config()
        transport_calls = []

        def transport(url, body, key, timeout):
            transport_calls.append(body)
            return dict(answers={q: dict(type='score', score=1.8) for q in body['questions']})

        # 1. Populate the cache with valid credentials
        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'test-key'}):
            first = j.evaluate(self.vault, 'query', self.cards, transport=transport)
            self.assertFalse(first['degraded'])
            self.assertFalse(first['cache_hit'])
            self.assertEqual(len(transport_calls), 1)

        # 2. On second call, simulate configuration changing at cache inspection (line 416)
        calls = [0]
        original_inspect = j.inspect_config

        def changing_inspect(vault):
            calls[0] += 1
            res = original_inspect(vault)
            # Call 1 is initial load (line 342), Call 2 is policy check (line 403).
            # Call 3 is the cache read race check (line 416).
            if calls[0] >= 3:
                res = dict(res, policy_revision='changed_policy_revision')
            return res

        # Run without API key to prove it doesn't fall through to credentials check or network
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(j, 'inspect_config', side_effect=changing_inspect):
                second = j.evaluate(self.vault, 'query', self.cards, transport=transport)
                self.assertTrue(second['degraded'])
                self.assertEqual(second['diagnostics'], ['configuration_changed'])
                self.assertNotIn('cache_unavailable', second['diagnostics'])
                self.assertNotIn('credentials_missing', second['diagnostics'])
                # No additional transport calls must occur
                self.assertEqual(len(transport_calls), 1)

    def test_cache_hit_race_at_final_check_aborts_without_stale_scores(self):
        """If configuration changes at line 427, cached scores must be cleared and diagnostics clean."""
        self.config()
        transport_calls = []

        def transport(url, body, key, timeout):
            transport_calls.append(body)
            return dict(answers={q: dict(type='score', score=1.8) for q in body['questions']})

        with patch.dict(os.environ, {'TYPESAFE_API_KEY': 'test-key'}):
            first = j.evaluate(self.vault, 'query', self.cards, transport=transport)
            self.assertFalse(first['degraded'])

        calls = [0]
        original_inspect = j.inspect_config

        def changing_inspect(vault):
            calls[0] += 1
            res = original_inspect(vault)
            # Call 4 is the final check right before cache_hit return (line 427)
            if calls[0] >= 4:
                res = dict(res, policy_revision='changed_policy_revision')
            return res

        with patch.dict(os.environ, {}, clear=True):
            with patch.object(j, 'inspect_config', side_effect=changing_inspect):
                second = j.evaluate(self.vault, 'query', self.cards, transport=transport)
                self.assertTrue(second['degraded'])
                self.assertEqual(second['scores'], {})
                self.assertEqual(second['diagnostics'], ['configuration_changed'])
                self.assertNotIn('cache_unavailable', second['diagnostics'])


if __name__ == '__main__':
    unittest.main()
