"""AutoDream faz 3 — merge adayı çözümleme, gövde görüşü ve kalıcı dismiss.

Spec: docs/specs/2026-09-26-autodream-phase3-merge-plan.md
Yol haritası: §5 adım 3, §4 (içerik ajanın), §5.1 (kod yalnız makineye ait olanı yazar)

Bu faz BULGU 8'i kapatır: birleştirilip aynı başlığı taşıyan bir işaretçi not
bırakıldığında aday kalıcı olarak yeniden çıkıyordu, çünkü eşleşme yalnız
başlığa bakıyordu ve "çözüldü" durumu tutulmuyordu.
"""
import datetime as dt
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / 'template/.claude/scripts'
CLI = ROOT / 'scripts/beyin_v3.py'
ARCHIVE = 'archive/auto-dream'
DISMISSED = 'archive/auto-dream/dismissed.json'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


def load_engine():
    spec = importlib.util.spec_from_file_location('dream3_engine', SCRIPTS / 'beyin_v3.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class DreamPhase3Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = load_engine()
        cls.dream = load('dream_phase3_subject', 'beyin_v3_dream.py')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='v3-dream-phase3-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / 'vault'
        self.vault.mkdir()
        self.state = self.root / 'state'
        self.store = self.engine.MemoryStore(self.state, self.vault)
        self.today = '2026-09-26'
        self.moment = dt.datetime.fromisoformat(f'{self.today}T10:00:00+00:00')

    # -- fixtures -------------------------------------------------------
    def write_note(self, relative, text, **meta):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        record = {'id': relative.replace('/', '-').replace('.md', ''), 'source': relative,
                  'text': text, 'kind': meta.get('kind', 'note'),
                  'status': meta.get('status', 'active'),
                  'visibility': 'internal', 'revision': 1}
        self.store.ingest(record)
        return relative

    def seed_citations(self, counts):
        import sqlite3
        db = sqlite3.connect(self.state / 'memory.sqlite3')
        try:
            for i, (source, times) in enumerate(counts.items()):
                for n in range(times):
                    db.execute('INSERT OR REPLACE INTO receipts VALUES (?,?)',
                               (f'r{i}-{n}', json.dumps({
                                   'event_id': f'r{i}-{n}', 'summary': 's', 'refs': [source],
                                   'harness': 'codex', 'created_at': self.moment.isoformat()})))
            db.commit()
        finally:
            db.close()

    def pairs(self):
        """Reported merge pairs as order-free sets.

        frozenset, tuple degil: kaynaklar sirali doner ve duzeltilmemis bir test
        sirayi karsilastirarak sessizce yesile doner (bu dosyada oldu).
        """
        state, _notice = self.dream.dismissed(self.vault)
        return {frozenset(pair['sources'])
                for pair in self.dream.candidates(
                    self.vault, self.store, self.store.receipt_stats()['citations'],
                    self.dream.inventory(self.vault)['oversize'], now=self.moment,
                    dismissed=state)['merge']}

    def merged_note(self, relative='knowledge/concepts/odeme-yontemi.md', body=None):
        """A merged note is what several notes left behind: several hundred characters.

        The stub ratio is only meaningful against a realistic target; a 200 character
        'merged' note made a one-line pointer look like a real note, and the rule
        correctly refused to silence it.
        """
        return self.write_note(relative, '# Ödeme Yöntemi\n\n' + (body or (
            'Stripe Checkout kullanılacak. Webhook idempotency anahtarı ile korunacak.\n'
            'Panelden aylık rapor alınacak. Müşteri onayı alındı.\n'
            'Sürdürme notu: retry politikası webhook notunda.\n'
            'Kurulum notu: test modunda sanal kartlarla doğrulandı.\n'
            'Vergi notu: fatura kesme işi ayrı bir görev olarak tutuluyor.\n')))

    def duplicate_note(self, relative='knowledge/concepts/odeme-yontemi-ek.md'):
        return self.write_note(relative, '# Ödeme Yöntemi (ek)\n\n' + (
            'Stripe Checkout kullanılacak. Webhook idempotency anahtarı ile korunacak.\n'
            'Sürdürme notu: retry politikası webhook notunda.\n'))

    # -- 1-3: gövde görüşü ---------------------------------------------
    def test_body_overlap_proposes_a_pair_whose_titles_differ(self):
        first = self.merged_note()
        second = self.write_note('knowledge/concepts/odeme-notu.md', '# Ödeme Tercihi\n\n' + (
            'Stripe Checkout kullanılacak. Webhook idempotency anahtarı ile korunacak.\n'
            'Panelden aylık rapor alınacak. Müşteri onayı alındı.\n'
            'Sürdürme notu: retry politikası webhook notunda.\n'))
        self.seed_citations({first: 2, second: 1})
        self.assertIn(frozenset((first, second)), self.pairs(),
                      'ayni konuda farkli baslikli iki not aday olmadi')

    def test_title_subset_behaviour_is_preserved(self):
        first = self.merged_note()
        second = self.duplicate_note()
        self.seed_citations({first: 2, second: 1})
        self.assertIn(frozenset((first, second)), self.pairs(), 'baslik alt-kumesi davranisi bozuldu')

    def test_a_note_is_never_paired_with_a_task(self):
        # Govde kurali her yerde benzerlik bulur; bir not ve bir gorev benzer konusur
        # ama birlestirilemezler (birlestirme bir iddiyi birlestirir, gorevi degil).
        note = self.write_note('knowledge/concepts/odeme-yontemi.md', '# Ödeme Yöntemi\n\n'
                               + ('Stripe Checkout ve webhook idempotency anahtarı. ' * 12))
        task = self.write_note('tasks/odeme-sayfasi.md', '# Ödeme Sayfası\n\n'
                               + ('Stripe Checkout entegrasyonunu sayfaya ekle. ' * 12),
                               kind='task', status='active')
        self.seed_citations({note: 2, task: 1})
        self.assertEqual(self.pairs(), set(), 'not ve gorev eslesmis')

    def test_unrelated_notes_are_never_paired(self):
        first = self.write_note('knowledge/concepts/odeme.md', '# Ödeme\n\nStripe Checkout ödemesi.\n')
        second = self.write_note('knowledge/concepts/kahve.md', '# Kahve\n\n'
                                 'Demir Kahve için menü düzeni, cihaz kurulumu ve kavrama.\n')
        self.seed_citations({first: 2, second: 1})
        self.assertNotIn(frozenset((first, second)), self.pairs(), 'ilgisiz iki not eslesmis')

    # -- 4-6: işaretçi tespiri (BULGU 8) --------------------------------
    def test_a_pointer_stub_is_not_proposed_again(self):
        # Birlesik not + AYNI BASLIGI tasiyan isaretci: bugun kalici olarak onerilir.
        first = self.merged_note()
        stub = self.write_note('knowledge/concepts/odeme-eski.md', '# Ödeme Yöntemi (eski)\n\n'
                               'Bu konu birleştirildi, güncel not: knowledge/concepts/odeme-yontemi.md\n')
        self.seed_citations({first: 2, stub: 1})
        self.assertNotIn(frozenset((first, stub)), self.pairs(), 'isaretci not tekrar onerildi')

    def test_a_short_note_without_a_pointer_is_still_proposed(self):
        # Asiri susturmama: kisalik tek basina isaretci sayilmaz.
        first = self.merged_note()
        second = self.write_note('knowledge/concepts/odeme-ozet.md', '# Ödeme\n\nStripe Checkout.\n')
        self.seed_citations({first: 2, second: 1})
        self.assertIn(frozenset((first, second)), self.pairs(), 'isaretci olmayan kisa not susturuldu')

    def test_a_pointer_sized_note_longer_than_the_cap_is_still_proposed(self):
        # Gercek bir not digerinin yolunu anar VE ayni iddiayi uzun uzun yazar. Iki
        # kanit birden var: hedefin yolunu aniyor, yalnizca kisa olmadigi icin isaretci
        # sayilmamali ve aday kalmali.
        first = self.merged_note()
        body = ('Bu not odeme yontemi notunu ayrintili olarak ele alir; '
                'knowledge/concepts/odeme-yontemi.md adresine bakin. '
                'Stripe Checkout kullanılacak. Webhook idempotency anahtarı ile korunacak. ')
        second = self.write_note('knowledge/concepts/odeme-notu.md', '# Ödeme\n\n' + body * 8)
        self.seed_citations({first: 2, second: 1})
        self.assertIn(frozenset((first, second)), self.pairs(), 'isaretci olmayan uzun not susturuldu')

    # -- 7-10: dismiss --------------------------------------------------
    def test_a_dismissed_pair_is_not_proposed_again(self):
        first = self.merged_note()
        second = self.duplicate_note()
        self.seed_citations({first: 2, second: 1})
        self.assertIn(frozenset((first, second)), self.pairs())
        self.dream.dismiss(self.vault, [first, second], now=self.moment)
        self.assertEqual(self.pairs(), set(), 'dismiss edilen cift tekrar onerildi')

    def test_dismissal_is_persistent_and_durable(self):
        first = self.merged_note()
        second = self.duplicate_note()
        self.seed_citations({first: 2, second: 1})
        self.dream.dismiss(self.vault, [first, second], now=self.moment)
        stored = json.loads((self.vault / DISMISSED).read_text(encoding='utf-8'))
        self.assertEqual(stored['schema'], 1)
        self.assertEqual(sorted(stored['pairs'][0]), sorted((first, second)))
        # Yeni store ve yeni pencere: sessizlik kalici.
        self.store.close()
        self.store = self.engine.MemoryStore(self.state, self.vault)
        self.addCleanup(self.store.close)
        self.assertEqual(self.pairs(), set())

    def test_dismissing_one_note_silences_every_pair_it_is_in(self):
        first = self.merged_note()
        second = self.duplicate_note()
        third = self.write_note('knowledge/concepts/odeme-yontemi-ek2.md', '# Ödeme Yöntemi Ek\n\n'
                                'Stripe Checkout ve webhook idempotency anahtarı ile korunacak.\n'
                                'Panelden aylık rapor alınacak. Müşteri onayı alındı.\n'
                                'Sürdürme notu: retry politikası webhook notunda.\n')
        self.seed_citations({first: 2, second: 1, third: 1})
        self.dream.dismiss(self.vault, [first], now=self.moment)
        remaining = self.pairs()
        self.assertEqual({pair for pair in remaining if first in pair}, set(),
                         'tek yol formu bu notun tum ciftlerini susturmadi')
        # Ve geri kalanlar duruyor: dismiss bir notu degil, o notun ciftlerini susturur.
        self.assertTrue(remaining, 'dismiss butun adaylari yok etmemeli')

    def test_a_broken_dismiss_file_does_not_stop_the_window(self):
        first = self.merged_note()
        second = self.duplicate_note()
        self.seed_citations({first: 2, second: 1})
        path = self.vault / DISMISSED
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{bu bir json degil', encoding='utf-8')
        result = self.dream.window(self.vault, self.state, self.store, now=self.moment)
        self.assertIn('dismiss', json.dumps(result, ensure_ascii=False).lower())
        self.assertTrue(result['wrote'] is False or result['applied'] is not None)

    # -- 11-13: --apply yüzeyi ------------------------------------------
    def test_apply_snapshots_both_notes_and_writes_no_body(self):
        first = self.merged_note()
        second = self.duplicate_note()
        self.seed_citations({first: 2, second: 1})
        before = {first: (self.vault / first).read_bytes(), second: (self.vault / second).read_bytes()}
        result = self.dream.window(self.vault, self.state, self.store, now=self.moment, force=True)
        self.assertTrue(result['wrote'], result)
        archived = {entry['source'] for entry in result['snapshot']['files']}
        self.assertIn(first, archived)
        self.assertIn(second, archived)
        # Govdeye dokunulmadi: icerik ajanin isi.
        self.assertEqual((self.vault / first).read_bytes(), before[first])
        self.assertEqual((self.vault / second).read_bytes(), before[second])
        plan = (self.vault / ARCHIVE / self.today / 'merge-plan.md')
        self.assertTrue(plan.is_file(), 'merge plani yazilmadi')
        text = plan.read_text(encoding='utf-8')
        self.assertIn(first, text)
        self.assertIn(second, text)
        # Plan dosyasi Turkce ve ajana yazilir: eslesme gerekcesi ve ortak sozcukler acikca yazilir.
        self.assertIn('ortak sözcükler', text)
        self.assertIn('eşleşme', text)
        self.assertIn('gövdelerini değiştirmedi', text)

    def test_restore_returns_both_merged_notes_byte_identically(self):
        first = self.merged_note()
        second = self.duplicate_note()
        self.seed_citations({first: 2, second: 1})
        before = {first: (self.vault / first).read_bytes(), second: (self.vault / second).read_bytes()}
        self.dream.window(self.vault, self.state, self.store, now=self.moment, force=True)
        self.dream.restore(self.vault, self.today)
        for source, data in before.items():
            self.assertEqual((self.vault / source).read_bytes(), data, f'{source} geri alinamadi')

    def test_cli_dismiss_and_apply_round_trip(self):
        first = self.merged_note()
        second = self.duplicate_note()
        self.seed_citations({first: 2, second: 1})
        applied = self.run_cli('dream', '--apply', '--force')
        self.assertEqual(applied['returncode'], 0, applied['stderr'])
        payload = json.loads(applied['stdout'])
        self.assertTrue(payload['wrote'], payload)
        self.assertTrue(payload['merge_plan_path'], payload)
        dismissed = self.run_cli('dream', '--dismiss', first, second)
        self.assertEqual(dismissed['returncode'], 0, dismissed['stderr'])
        self.assertIn(sorted((first, second)),
                      [sorted(pair) for pair in json.loads(dismissed['stdout'])['dismissed']['pairs']])
        report = self.run_cli('dream')
        self.assertEqual(report['returncode'], 0, report['stderr'])
        self.assertEqual(json.loads(report['stdout'])['candidates']['merge'], [])

    def test_a_snapshot_is_never_indexed_as_memory(self):
        # CLI --apply sonrasi bir sync kostu: kurtarma kiti vault'ta bekliyor. Indeks
        # onu gorurse her on-image bir not olur ve kaynak notun KENDISIYLE adaylasir.
        first = self.merged_note()
        second = self.duplicate_note()
        self.seed_citations({first: 2, second: 1})
        self.assertEqual(self.run_cli('dream', '--apply', '--force')['returncode'], 0)
        sources = {record['source'] for record in self.store.list_records()}
        self.assertFalse([source for source in sources if source.startswith('archive/')],
                         'kurtarma kiti indekslendi: ' + str(sorted(sources)))
        for pair in self.pairs():
            self.assertNotEqual(tuple(pair)[0], tuple(pair)[1], 'not kendi kopyasiyla eslesmesi')
        self.assertEqual(self.run_cli('dream')['returncode'], 0)

    def run_cli(self, *args):
        result = subprocess.run([sys.executable, str(CLI), '--vault', str(self.vault),
                                 '--state', str(self.state), *args],
                                capture_output=True, text=True, timeout=120,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        return {'returncode': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr}


if __name__ == '__main__':
    unittest.main()
