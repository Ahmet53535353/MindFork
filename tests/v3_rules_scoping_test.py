"""Unit tests for rule scoping and dynamic rule layering (Issue #288 Item 1)."""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))
import beyin_v3_companion as companion
import beyin_v3 as runtime

COMPANION = '🔮 850-Companion'


class RulesScopingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-scoping-')
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name) / 'vault'
        (self.vault / COMPANION).mkdir(parents=True)
        self.state = Path(self.tmp.name) / 'state'
        self.state.mkdir()
        self.store = runtime.MemoryStore(self.state, self.vault)

    def seed(self, kurallar):
        notes = {
            'Core.md': '# Core\nKimlik.\n',
            'Last-Session.md': '## 2026-10-12 00:00 · etiket · abcd1234\nDevir.\n',
            'Threads.md': '## Active Threads\n### Thread: T1\n**Status:** active\n',
            'Journal.md': '# Journal\n## 2026-10-12\nNot.\n',
            'Kurallar.md': kurallar,
        }
        for name, body in notes.items():
            source = f'{COMPANION}/{name}'
            (self.vault / source).write_text(body, encoding='utf-8')
            self.store.ingest({'id': name, 'kind': 'note', 'status': 'active', 'text': body,
                               'source': source, 'updated_at': '2026-10-12T00:00:00Z'})

    def test_rule_scopes_parsing(self):
        self.assertEqual(companion.rule_scopes('- Genel kural'), set())
        self.assertEqual(companion.rule_scopes('- [scope: global] Genel kural'), set())
        self.assertEqual(companion.rule_scopes('- [kapsam: genel] Genel kural'), set())
        self.assertEqual(companion.rule_scopes('- [scope: backend] Sadece backend kuralı'), {'backend'})
        self.assertEqual(companion.rule_scopes('- [kapsam: frontend, ui] UI kuralı'), {'frontend', 'ui'})
        self.assertEqual(companion.rule_scopes('- scope: mobile Mobil kural'), {'mobile'})

    def test_filter_scoped_rules_without_active_project_keeps_all(self):
        text = (
            "# Kurallar\n\n"
            "- Genel kural bir.\n"
            "- [scope: backend] Backend kuralı.\n"
            "- [scope: frontend] Frontend kuralı.\n"
        )
        self.assertEqual(companion.filter_scoped_rules(text, active_project=None), text)
        self.assertEqual(companion.filter_scoped_rules(text, active_project=""), text)

    def test_filter_scoped_rules_with_active_project(self):
        text = (
            "# Kurallar\n\n"
            "- Genel kural bir.\n\n"
            "- [scope: backend] Backend kuralı.\n\n"
            "- [scope: frontend] Frontend kuralı.\n\n"
            "- [kapsam: backend, infra] Altyapı kuralı.\n"
        )
        filtered_backend = companion.filter_scoped_rules(text, active_project="backend")
        self.assertIn("Genel kural bir", filtered_backend)
        self.assertIn("Backend kuralı", filtered_backend)
        self.assertIn("Altyapı kuralı", filtered_backend)
        self.assertNotIn("Frontend kuralı", filtered_backend)

        filtered_frontend = companion.filter_scoped_rules(text, active_project="frontend")
        self.assertIn("Genel kural bir", filtered_frontend)
        self.assertIn("Frontend kuralı", filtered_frontend)
        self.assertNotIn("Backend kuralı", filtered_frontend)
        self.assertNotIn("Altyapı kuralı", filtered_frontend)

    def test_project_folder_rules_are_loaded_into_companion_context(self):
        self.seed('# Kurallar\n- Global kural\n')

        # Create project specific rules in projects/alpha/Kurallar.md
        proj = self.vault / 'projects' / 'alpha'
        proj.mkdir(parents=True)
        (proj / 'Kurallar.md').write_text('# Alpha Kuralları\n- Alpha özel kuralı\n', encoding='utf-8')


        # Without project, project rules are not loaded
        ctx_no_proj = companion.context(self.store, 8000, 'session-1', 'claude', project=None)
        self.assertNotIn('Alpha özel kuralı', ctx_no_proj)
        self.assertIn('Global kural', ctx_no_proj)

        self.store.ingest({'id': 'project-rule', 'kind': 'note', 'status': 'active',
                           'source': 'projects/alpha/Kurallar.md',
                           'text': '# Alpha Kuralları\n- Alpha özel kuralı\n', 'updated_at': '2026-10-12T00:00:00Z'})

        # With project='alpha', project rules are loaded into companion context
        ctx_proj = companion.context(self.store, 8000, 'session-1', 'claude', project='alpha')
        self.assertIn('[projects/alpha/Kurallar.md]', ctx_proj)
        self.assertIn('Alpha özel kuralı', ctx_proj)

    def test_private_unindexed_and_changed_project_rules_are_not_delivered(self):
        self.seed('# Kurallar\n- Global kural\n')
        source = 'projects/alpha/Kurallar.md'
        target = self.vault / source
        target.parent.mkdir(parents=True)
        target.write_text('- PRIVATE-MARKER', encoding='utf-8')
        self.assertNotIn('PRIVATE-MARKER', companion.context(self.store, 8000, 's', 'claude', project='alpha'))
        self.store.ingest({'id': 'private-rule', 'kind': 'note', 'status': 'active',
                           'source': source, 'text': '- PRIVATE-MARKER', 'visibility': 'private',
                           'updated_at': '2026-10-12T00:00:00Z'})
        self.assertNotIn('PRIVATE-MARKER', companion.context(self.store, 8000, 's', 'claude', project='alpha'))

    def test_project_symlink_alias_does_not_deliver_another_project_rules(self):
        self.seed('# Kurallar\n- Global kural\n')
        target = self.vault / 'projects/beta/Kurallar.md'
        target.parent.mkdir(parents=True)
        target.write_text('- BETA-MARKER', encoding='utf-8')
        self.store.ingest({'id': 'beta-rule', 'kind': 'note', 'status': 'active',
                           'source': 'projects/beta/Kurallar.md', 'text': '- BETA-MARKER',
                           'updated_at': '2026-10-12T00:00:00Z'})
        try:
            (self.vault / 'projects/alpha').symlink_to(target.parent, target_is_directory=True)
        except OSError as exc:
            self.skipTest(str(exc))
        text = companion.context(self.store, 8000, 's', 'claude', project='alpha')
        self.assertNotIn('BETA-MARKER', text)

    def test_turkish_scope_matching(self):
        text = '- [kapsam: ARŞİV] Kural\n- [scope: backend] Other'
        self.assertIn('Kural', companion.filter_scoped_rules(text, 'arşiv'))
        self.assertIn('Kural', companion.filter_scoped_rules(text, 'arsiv'))
        self.assertNotIn('Other', companion.filter_scoped_rules(text, 'arşiv'))

    def test_path_traversal_project_is_safely_ignored(self):
        self.seed('# Kurallar\n- Global kural\n')

        # Malicious project path attempting traversal outside vault
        ctx_traversal = companion.context(self.store, 8000, 'session-1', 'claude', project='../../outside')
        self.assertIn('Global kural', ctx_traversal)
        # Should not raise any error and not escape vault


if __name__ == '__main__':
    unittest.main()
