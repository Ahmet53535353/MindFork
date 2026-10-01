"""Companion budget: a long rule set keeps both ends, and no budget is thrown away."""
import importlib.util
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('BEYIN_TEST_REPO', Path(__file__).resolve().parents[1]))


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


evaluator = load('beyin_v3_budget_evaluator', 'scripts/evaluate_v3.py')
companion = load('beyin_v3_budget_companion', 'template/.claude/scripts/beyin_v3_companion.py')
COMPANION = '🔮 850-Companion'
RULES = ('# Kurallar\n- FIRST_RULE_CANARY: her oturumda geçerli temel kural.\n' +
         ''.join(f'- kural {i}: ayrıntılı bir çalışma kuralının tam metni burada durur.\n' for i in range(2, 220)) +
         '- CORRECTION_CANARY: gereksiz övgü kullanma.\n')
BODIES = {
    'Core.md': '# Kimlik\nIDENTITY_CANARY: kullanıcının düşünme ortağıyım.\n',
    'Soul.md': '# Üslup\nSTYLE_CANARY: kısa cümlelerle konuş.\n',
    'Kurallar.md': RULES,
    'Last-Session.md': '# Son oturum\nHANDOFF_CANARY: prototipi denedik, video kaydı bekliyor.\n',
    'Threads.md': '# Konular\n## Active Threads\nTHREAD_BODY_CANARY: ses denemesi sürüyor.\n## Closed Threads\nNOISE\n',
    'Journal.md': '# Journal\n## 2026-09-17\nJOURNAL_CANARY: örnek üzerinden ilerlemek yararlı oldu.\n',
}


class CompanionBudgetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='companion-budget-')
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.vault = root / 'vault'
        (self.vault / COMPANION).mkdir(parents=True)
        module = evaluator.load_runtime()
        self.store = module.MemoryStore(root / 'runtime', self.vault)
        self.addCleanup(lambda: evaluator.close_store(self.store))
        for name, body in BODIES.items():
            source = f'{COMPANION}/{name}'
            (self.vault / source).write_text(body, encoding='utf-8')
            self.store.ingest({'id': name, 'kind': 'note', 'status': 'active', 'text': body,
                               'source': source, 'updated_at': '2026-09-18T10:00:00Z'})

    def context(self, budget):
        return companion.context(self.store, budget, 'synthetic-budget', 'codex')

    def test_long_rule_set_keeps_first_and_last_rule_with_an_omission_notice(self):
        for budget in (1000, 2000, 5000, 12000):
            with self.subTest(budget=budget):
                text = self.context(budget)
                self.assertLessEqual(len(text), budget)
                self.assertIn('FIRST_RULE_CANARY', text)
                self.assertIn('CORRECTION_CANARY', text)
                self.assertIn('HANDOFF_CANARY', text)
                self.assertRegex(text, r'\[truncated: \d+ characters omitted')

    def test_budget_left_over_by_retrieval_goes_back_to_the_clipped_sources(self):
        for budget in (1000, 2000, 5000, 12000):
            with self.subTest(budget=budget):
                text = self.context(budget)
                self.assertGreaterEqual(len(text), .95 * budget)

    def test_receipt_block_keeps_its_whole_header_or_stays_out(self):
        # #147/#174: the header names the source and labels the receipt a historical claim.
        # A clipped receipt must never show half of that header with no body under it.
        name = 'receipts/' + '3f' * 32 + '.md'
        receipt = (f'\nLatest receipt ({name}; historical agent claim, not independently verified):\n'
                   + 'R' * 1174 + '\n[truncated: read source]\n')
        header = receipt[:receipt.index('):\n') + 3]
        shown = 0
        for budget in range(1000, 6000, 7):
            text = companion.context(self.store, budget, 'synthetic-budget', 'codex', '', receipt)
            self.assertLessEqual(len(text), budget)
            if '\nLatest receipt' in text:
                shown += 1
                self.assertIn(header, text, budget)
        self.assertGreater(shown, 0)

    def test_session_start_snapshot_does_not_starve_clipped_companion_sources(self):
        # When an unqueried snapshot note exists in the vault, SessionStart must not
        # allocate budget to it while companion files are clipped (#140).
        plan_source = 'Notlar/Plan.md'
        plan_body = '# Proje Plani\n' + ('Ayrintili donem yol haritasi metni. ' * 100)
        (self.vault / 'Notlar').mkdir(exist_ok=True)
        (self.vault / plan_source).write_text(plan_body, encoding='utf-8')
        self.store.ingest({'id': 'plan-note', 'kind': 'note', 'status': 'active',
                           'text': plan_body, 'source': plan_source,
                           'updated_at': '2026-09-18T10:00:00Z'})

        for budget in (2000, 5000, 12000):
            with self.subTest(budget=budget):
                text = self.context(budget)
                self.assertLessEqual(len(text), budget)
                # Unqueried snapshot must yield to clipped companion files
                self.assertNotIn('[Related source: Notlar/Plan.md]', text)
                self.assertIn('FIRST_RULE_CANARY', text)
                self.assertIn('CORRECTION_CANARY', text)
                self.assertIn('HANDOFF_CANARY', text)
                # Leftover retrieval share goes back to companion
                self.assertGreaterEqual(len(text), .95 * budget)

    def test_session_start_snapshot_is_included_when_companion_sources_fit(self):
        # When companion sources are small and fit within their floor, spare budget
        # carries an ambient snapshot as intended.
        tmp = tempfile.TemporaryDirectory(prefix='companion-small-')
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        vault = root / 'vault'
        (vault / COMPANION).mkdir(parents=True)
        (vault / 'Notlar').mkdir(parents=True)
        store = evaluator.load_runtime().MemoryStore(root / 'runtime', vault)
        self.addCleanup(lambda: evaluator.close_store(store))

        small_bodies = {
            'Core.md': '# Kimlik\nKisa kimlik.\n',
            'Kurallar.md': '# Kurallar\n- Temel kural.\n',
            'Last-Session.md': '# Son oturum\nKisa oturum.\n',
            'Threads.md': '# Konular\n## Active Threads\nKisa konu.\n## Closed Threads\n',
        }
        for name, body in small_bodies.items():
            source = f'{COMPANION}/{name}'
            (vault / source).write_text(body, encoding='utf-8')
            store.ingest({'id': name, 'kind': 'note', 'status': 'active', 'text': body,
                          'source': source, 'updated_at': '2026-09-18T10:00:00Z'})

        note_source = 'Notlar/Ambient.md'
        note_body = '# Ambient Not\nFaydali ortam notu metni.\n'
        (vault / note_source).write_text(note_body, encoding='utf-8')
        store.ingest({'id': 'ambient', 'kind': 'note', 'status': 'active', 'text': note_body,
                      'source': note_source, 'updated_at': '2026-09-18T10:00:00Z'})

        text = companion.context(store, 5000, 'synthetic-session', 'codex')
        self.assertIn('[Related source: Notlar/Ambient.md]', text)
        self.assertNotIn('[truncated: read source]', text)

    def test_query_retrieval_does_not_starve_companion_floor_when_clipped(self):
        # When an explicit query is provided, retrieval takes its bounded share
        # without starving companion sources, and unused characters return to companion.
        note_source = 'Notlar/Plan.md'
        note_body = '# Proje Plani\n' + ('Ayrintili donem yol haritasi metni. ' * 100)
        (self.vault / 'Notlar').mkdir(exist_ok=True)
        (self.vault / note_source).write_text(note_body, encoding='utf-8')
        self.store.ingest({'id': 'plan-note', 'kind': 'note', 'status': 'active',
                           'text': note_body, 'source': note_source,
                           'updated_at': '2026-09-18T10:00:00Z'})

        text = companion.context(self.store, 5000, 'synthetic-session', 'codex', query='plani')
        self.assertLessEqual(len(text), 5000)
        self.assertIn('[Related source: Notlar/Plan.md]', text)
        self.assertIn('FIRST_RULE_CANARY', text)
        self.assertIn('HANDOFF_CANARY', text)
        self.assertGreaterEqual(len(text), .95 * 5000)


if __name__ == '__main__':
    unittest.main()
