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
    'memory-types.md': '# Memory Types\nMEMORY_TYPES_CANARY\n',
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

    rewrites = 0

    def rewrite(self, name, body):
        """Replace one companion source and re-index it as a newer revision of that source."""
        type(self).rewrites += 1
        source = f'{COMPANION}/{name}'
        (self.vault / source).write_text(body, encoding='utf-8')
        self.store.ingest({'id': f'{name}-r{type(self).rewrites}', 'kind': 'note', 'status': 'active',
                           'text': body, 'source': source, 'updated_at': '2026-09-19T10:00:00Z'})


class RulesSurviveLargeThreadIndexTest(CompanionBudgetTest):
    """Where the context budget actually starts costing the user their rules.

    The month E2E reported "Threads.md grows and eats the context budget, rules get
    truncated". Measured against the real code the report was too strong, and the truth is
    worth pinning: the water-fill walks NAMES in order, so at a normal 5000-character
    budget nothing is clipped at all, and the clip point is a function of the budget, not
    of the thread index. Below it, clipping is correct behaviour but must stay visible
    (an omission marker), keep the newest rule and the handoff card, and stay in budget.
    """
    RULES = ('# Kurallar\n' + ''.join(
        f'- RULE_{i}_CANARY: ' + ('gercek bir calisma kuralinin ayrintili metni. ' * 12) + '\n'
        for i in (1, 2, 3)))
    THREADS = ('# Konular\n## Active Threads\n' +
               ''.join(f'- konu {i}: uzun bir acik konu basligi ve detayi burada.\n' for i in range(1, 150)) +
               '## Closed Threads\n')

    def large_index_state(self):
        self.rewrite('Kurallar.md', self.RULES)
        self.rewrite('Threads.md', self.THREADS)

    def test_at_the_normal_budget_nothing_a_turn_needs_is_clipped(self):
        self.large_index_state()
        text = self.context(5000)
        self.assertLessEqual(len(text), 5000)
        for i in (1, 2, 3):
            self.assertIn(f'RULE_{i}_CANARY', text, f'kural {i} butce icinde kalkti')
        self.assertIn('HANDOFF_CANARY', text, 'devir karti kalkti')
        self.assertIn('IDENTITY_CANARY', text, 'kimlik dosyasi kalkti')
        self.assertNotIn('characters omitted', text, 'butce yeterliyken kirpma yapildi')

    def test_below_the_clip_point_the_loss_is_visible_and_keeps_the_newest_rule(self):
        self.large_index_state()
        for budget in (3000, 2000):
            with self.subTest(budget=budget):
                text = self.context(budget)
                self.assertLessEqual(len(text), budget)
                self.assertRegex(text, r'characters omitted',
                                 'kirpma kullaniciya gorunmez sekilde olmamali')
                self.assertIn('RULE_3_CANARY', text, 'en yeni kural kirpilmada kaybolmamali')
                self.assertIn('HANDOFF_CANARY', text, 'devir karti kirpilmada kaybolmamali')

    def test_the_thread_index_never_outranks_the_rules(self):
        # Konu dizini 8 bin karaktere yakin buyusun de kurallar butceye girer.
        self.large_index_state()
        text = self.context(5000)
        self.assertGreater(len(self.THREADS), 6000)
        self.assertIn('RULE_3_CANARY', text)
        self.assertNotIn('- konu 149', text, 'konu dizini butceyi kurallardan once doldurdu')


if __name__ == '__main__':
    unittest.main()
