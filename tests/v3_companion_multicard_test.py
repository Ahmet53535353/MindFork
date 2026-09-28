"""Companion handoff cards (#118): the newest card arrives whole and no card is split.

Upstream made the handoff one card per session and taught the archiver to move a card as a
whole unit (beyin_v3_compact.py: "a card moves or stays whole"). The context path was left
behind: FLOORS still shares Last-Session.md out as a flat character budget and clip() cut it
head-only, so a card that did not fit lost its tail -- the "next concrete step" line, the one
line a handoff exists for. These tests pin the whole-card contract on the context side.
"""
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


evaluator = load('beyin_v3_multicard_evaluator', 'scripts/evaluate_v3.py')
companion = load('beyin_v3_multicard_companion', 'template/.claude/scripts/beyin_v3_companion.py')
COMPANION = '🔮 850-Companion'
FILLER = 'Karar gerekçesi, kaynak bağlantısı ve açık kalan adım burada ayrıntılı olarak anlatılıyor. '


def handoff(cards):
    """A handoff file in the shape SKILL.md mandates: newest card on top, then older ones."""
    parts = ['# Son oturum\n\n']
    for tag, moment, session in cards:
        parts.append(f'## {moment} · {tag} etiketi · {session}\n'
                     f'HEAD_{tag}: oturumda {tag} işi yapıldı.\n'
                     f'{FILLER * 4}'
                     f'TAIL_{tag}: Sonraki somut adım: {tag} adımını yaz.\n\n')
    return ''.join(parts)


CARDS = [('YENI', '2026-09-27 15:10', 'aaaaaaaa'),
         ('ORTA', '2026-09-27 10:32', 'bbbbbbbb'),
         ('ESKI', '2026-09-26 18:05', 'cccccccc')]
TAGS = [tag for tag, _, _ in CARDS]
BASE = {
    'Core.md': '# Kimlik\nIDENTITY_CANARY: kullanıcının düşünme ortağıyım.\n',
    'Soul.md': '# Üslup\nSTYLE_CANARY: kısa cümlelerle konuş.\n',
    'Kurallar.md': '# Kurallar\n- FIRST_RULE_CANARY: her oturumda geçerli temel kural.\n'
                    '- CORRECTION_CANARY: gereksiz övgü kullanma.\n',
    'Threads.md': '# Konular\n## Active Threads\nTHREAD_BODY_CANARY: ses denemesi sürüyor.\n## Closed Threads\n',
    'Journal.md': '# Journal\n## 2026-09-17\nJOURNAL_CANARY: örnek üzerinden ilerlemek yararlı oldu.\n',
    'memory-types.md': '# Memory Types\nMEMORY_TYPES_CANARY\n',
}
DROPPED = re.compile(r'\[truncated: (\d+) older handoff cards not shown')


class MulticardContextTest(unittest.TestCase):
    """The context path must honour the same whole-card rule as the archiver."""

    def build(self, last_session):
        self.tmp = tempfile.TemporaryDirectory(prefix='companion-multicard-')
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        vault = root / 'vault'
        (vault / COMPANION).mkdir(parents=True)
        module = evaluator.load_runtime()
        self.store = module.MemoryStore(root / 'runtime', vault)
        self.addCleanup(lambda: evaluator.close_store(self.store))
        bodies = dict(BASE, **{'Last-Session.md': last_session})
        for name, body in bodies.items():
            source = f'{COMPANION}/{name}'
            (vault / source).write_text(body, encoding='utf-8')
            self.store.ingest({'id': name, 'kind': 'note', 'status': 'active', 'text': body,
                               'source': source, 'updated_at': '2026-09-27T10:00:00Z'})

    def context(self, budget):
        return companion.context(self.store, budget, 'synthetic-multicard', 'codex')

    def shown_tags(self, text):
        return [tag for tag in TAGS if f'HEAD_{tag}' in text]

    def test_newest_card_arrives_whole_when_the_budget_is_tight(self):
        self.build(handoff(CARDS))
        for budget in (1200, 1500, 2000):
            with self.subTest(budget=budget):
                text = self.context(budget)
                self.assertLessEqual(len(text), budget)
                self.assertIn('HEAD_YENI', text)
                self.assertIn('TAIL_YENI', text)

    def test_economical_profile_keeps_the_next_step_of_the_newest_card(self):
        # 2000 is the economical and manual profile budget (preferences.PROFILES).
        self.build(handoff(CARDS))
        text = self.context(2000)
        self.assertIn('HEAD_YENI', text)
        self.assertIn('TAIL_YENI', text)

    def test_no_card_is_split_by_the_budget(self):
        cards = CARDS + [('DORT', '2026-09-25 09:00', 'dddddddd'), ('BES', '2026-09-24 09:00', 'eeeeeeee')]
        self.build(handoff(cards))
        for budget in (1200, 1600, 2000, 2600, 3400):
            with self.subTest(budget=budget):
                text = self.context(budget)
                for tag in [tag for tag, _, _ in cards]:
                    if f'HEAD_{tag}' in text:
                        self.assertIn(f'TAIL_{tag}', text, f'{tag} kartı başından kesildi')

    def test_cards_left_out_are_named_in_the_truncation_notice(self):
        cards = CARDS + [('DORT', '2026-09-25 09:00', 'dddddddd'), ('BES', '2026-09-24 09:00', 'eeeeeeee')]
        self.build(handoff(cards))
        text = self.context(1200)
        dropped = [tag for tag, _, _ in cards if f'HEAD_{tag}' not in text]
        self.assertTrue(dropped, 'bu bütçede kart düşmüyor, test ölçüm için geçersiz')
        self.assertRegex(text, rf'\[truncated: {len(dropped)} older handoff cards not shown')

    def test_normal_profile_still_delivers_every_card_whole(self):
        self.build(handoff(CARDS))
        text = self.context(5000)
        for tag in TAGS:
            with self.subTest(card=tag):
                self.assertIn(f'HEAD_{tag}', text)
                self.assertIn(f'TAIL_{tag}', text)

    def test_cards_are_ranked_by_date_not_by_file_position(self):
        # Hands-on finding (2026-09-27): an agent that appends its card at the end of the file
        # instead of opening one on top lost its own handoff from the context, and the notice
        # called the dropped cards "older" while they were the newest ones. The card list is
        # ordered by its own heading date, so either writing direction delivers the newest card.
        newest, middle, oldest = CARDS
        body = handoff([oldest, middle])          # 2026-09-26, 2026-09-27 10:32
        body += ('\n## 2026-09-27 23:50 · gece · SONKART\n'
                 'HEAD_SONKART: en sona eklenen kart.\n' + FILLER * 4 +
                 'TAIL_SONKART: Sonraki somut adım: gece işi.\n')
        self.build(body)
        for budget in (1200, 2000, 3400):
            with self.subTest(budget=budget):
                text = self.context(budget)
                self.assertIn('HEAD_SONKART', text, 'dosyanın sonundaki en yeni kart düştü')
                self.assertIn('TAIL_SONKART', text)
                if 'HEAD_ESKI' in text:            # older cards may still fit, never the newest
                    self.assertIn('HEAD_ORTA', text)

    def test_undated_card_heading_does_not_displace_the_newest_dated_card(self):
        # An old single-card handoff can carry a heading without a clock; it must not win the
        # budget over a dated card, and it must not crash the ranking.
        body = handoff(CARDS)
        self.build(body.rstrip() + '\n\n## Devir kartı (eski bicim)\nHEAD_ESKIBICIM: eski.\n')
        text = self.context(1200)
        self.assertIn('HEAD_YENI', text)
        self.assertIn('TAIL_YENI', text)

    def test_undated_card_in_the_newest_position_is_not_ranked_as_the_oldest(self):
        """The existing undated test appends its undated card at the end, where ranking it last
        is right; the dangerous direction is an undated card sitting where the newest one belongs.
        Ranking read only what it could compare, so such a card fell below genuinely older dated
        cards and lost its own slot in the budget -- the exact failure the date ranking was
        written to prevent, reached by a heading the parser cannot read.
        """
        older = handoff(CARDS[-2:])                 # 2026-09-27 10:32, then 2026-09-26 18:05
        newest = ('## Devir kartı\n'
                  'HEAD_TARIHSSIZ: dosyanın en üstündeki yeni kart.\n' + FILLER * 4 +
                  'TAIL_TARIHSSIZ: Sonraki somut adım: yeni kartın adımını yaz.\n\n')
        self.build(older.replace('# Son oturum\n\n', '# Son oturum\n\n' + newest, 1))
        for budget in (1200, 2000):
            with self.subTest(budget=budget):
                text = self.context(budget)
                self.assertIn('HEAD_TARIHSSIZ', text, 'en üstteki tarihsiz kart düştü')
                self.assertIn('TAIL_TARIHSSIZ', text)

    def test_legacy_single_card_with_previous_section_still_reads_correctly(self):
        legacy = ('# Son oturum\n\n'
                  '## 2026-09-20 09:00 · eski model · 1234abcd\n'
                  'LEGACY_HEAD: tek kart gövdesi.\n' + FILLER * 4 +
                  'LEGACY_TAIL: Sonraki adım: eski modeli bırak.\n\n'
                  '## Previous\nESKI_BOLUM: arşivlenmiş önceki oturumlar.\n')
        self.build(legacy)
        for budget in (1200, 2000, 5000):
            with self.subTest(budget=budget):
                text = self.context(budget)
                self.assertNotIn('ESKI_BOLUM', text)
                self.assertIn('LEGACY_HEAD', text)

    def test_file_without_cards_is_delivered_unchanged(self):
        flat = '# Son oturum\n\nHenüz bir çalışma sonucu kaydedilmedi.\n'
        self.build(flat)
        text = self.context(5000)
        self.assertIn('Henüz bir çalışma sonucu kaydedilmedi', text)


if __name__ == '__main__':
    unittest.main()
