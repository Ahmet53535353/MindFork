"""Kapı dar kalmalı mı, ölçülmesi gerekir. 2026-07-17'de ölçüldü:

* Tüm vault'u taramak **45 ms** (278 dosya, 2.1 MB) — daraltmanın maliyet gerekçesi yok.
* Motor `Last-Session.md` ve `Threads.md` için **hiçbir yazma çağrısı yapmıyor**
  (`beyin_v3_companion.py` yalnız durum dosyalarını yazıyor). Yani o dosyalara
  **girdi denetimi uygulanamaz**; tek koruma çıktı tarafı tarama.
* `notes/` içeriği ajandan **ve** `beyin_v3_yakala.py:398` üzerinden dışarıdan
  geliyor, yani o yolda da motor girdi denetimi yok.

Bu testler kapsamı dört kovaya böler ve her kovanın neyi yükseltmesi gerektiğini
sabitler: üretilmiş görüntü ve companion dosyaları yükseltir, çıplak kaynaklar
(ham yakalamalar, arşiv) ve değişmez receipt'ler yalnız bildirilir. Ham bir web
kopyasının kırık çit içermesi normaldir; onu BLOCKER yapmak doctor'u itibarsızlaştırır.
"""
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('BEYIN_TEST_REPO', Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))
import beyin_v3_projections as projections  # noqa: E402

BT = chr(96)
FENCE = BT * 3

BALANCED = 'Metin:\n\n' + FENCE + '\nkod\n' + FENCE + '\n\nDevam.'
UNBALANCED = 'Metin:\n\n' + FENCE + '\nkod\n\nDevam.'
COMPANION = '🔮 850-Companion'


class WidenedGateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='beyin-gate-')
        self.addCleanup(self._tmp.cleanup)
        self.vault = Path(self._tmp.name)
        self.write(f'{COMPANION}/Threads.md', BALANCED)
        self.write(f'{COMPANION}/Last-Session.md', BALANCED)
        self.write('daily/v3/2026-01-01.md', BALANCED)
        self.write('notes/normal.md', BALANCED)

    def write(self, relative, text):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def report(self):
        return projections.markdown_health(self.vault)

    def test_uretmemis_goruntu_kovasi_yukseltir(self):
        self.write('daily/v3/2026-01-01.md', UNBALANCED)
        r = self.report()
        self.assertEqual(r['status'], 'broken')
        self.assertIn('daily/v3/2026-01-01.md', [b['source'] for b in r['broken_generated']])

    def test_companion_dosyasi_kovasi_yukseltir(self):
        """Motor bu dosyayi yazmiyor; girdi denetimi uygulanamaz."""
        self.write(f'{COMPANION}/Last-Session.md', UNBALANCED)
        r = self.report()
        self.assertEqual(r['status'], 'broken', 'companion okunmaz hale gelince yukseltmeli')
        self.assertIn(f'{COMPANION}/Last-Session.md', [b['source'] for b in r['broken_companion']])

    def test_ciplak_kaynak_yalniz_bildirilir(self):
        """Ham yakalama kirik cit icerebilir; bu BLOCKER olmamali."""
        self.write('okuma/ham/kirpik.md', UNBALANCED)
        self.write('notlar/el.md', UNBALANCED)
        r = self.report()
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(len(r['broken_sources']), 2)

    def test_degismez_receipt_yalniz_bildirilir(self):
        self.write('receipts/abc.md', UNBALANCED)
        r = self.report()
        self.assertEqual(r['status'], 'ok')
        self.assertEqual([b['source'] for b in r['immutable_receipts']], ['receipts/abc.md'])

    def test_temiz_vault_ok_doner(self):
        r = self.report()
        self.assertEqual(r['status'], 'ok')
        self.assertEqual(r['broken_generated'], [])
        self.assertEqual(r['broken_companion'], [])
        self.assertEqual(r['scanned'], 4)

    def test_arsiv_kovasina_girer_ama_yukseltmez(self):
        self.write(f'{COMPANION}/Arşiv/Threads-2026-10.md', UNBALANCED)
        r = self.report()
        self.assertEqual(r['status'], 'ok')
        self.assertIn(f'{COMPANION}/Arşiv/Threads-2026-10.md',
                      [b['source'] for b in r['broken_sources']])

    def test_icerik_dil_dondurmez(self):
        self.write(f'{COMPANION}/Threads.md', UNBALANCED)
        self.report()
        self.assertEqual((self.vault / f'{COMPANION}/Threads.md').read_text(encoding='utf-8'), UNBALANCED)

    def test_gecici_ve_gizli_dizinler_taranmaz(self):
        self.write('.obsidian/calisma.md', UNBALANCED)
        self.write('node_modules/x/ok.md', UNBALANCED)
        r = self.report()
        self.assertEqual(r['scanned'], 4, 'gizli dizinler sayildi')

    def test_okuma_uyarisı_yazi_uretebilmeli(self):
        """Companion bağlamına verilecek tek satırlık uyarı."""
        self.write(f'{COMPANION}/Threads.md', UNBALANCED)
        self.write(f'{COMPANION}/Last-Session.md', BALANCED)
        line = projections.markdown_read_notice(self.vault)
        self.assertIn('Threads.md', line)
        self.assertNotIn('Last-Session.md', line)

    def test_okuma_uyarisı_vault_taramamali(self):
        """SessionStart bütçesi walk/rglob/glob sayacını sıfır bekliyor.

        İlk yazımda uyarı tüm vault'u tarıyordu ve tam olarak bu bütçeyi kırdı
        (ölçüldü: 1 rglob + 1 glob, `v3_perf_budget_test` kırmızı). Okuma yolunda
        yalnız yedi adlandırılmış companion dosyasına doğrudan bakılmalı.
        """
        self.write('notlar/derin/kirli.md', UNBALANCED)
        self.write('daily/v3/2026-02-02.md', UNBALANCED)
        # Path.walk yalnız Python 3.12+'da var; 3.11'de sayacı yok sayılır.
        kinds = ['rglob', 'glob'] + (['walk'] if hasattr(Path, 'walk') else [])
        counts = {k: 0 for k in kinds}
        original = {k: getattr(Path, k) for k in kinds}

        def counting(kind):
            def wrapper(self, *a, **kw):
                counts[kind] += 1
                return original[kind](self, *a, **kw)
            return wrapper

        for kind in counts:
            setattr(Path, kind, counting(kind))
        try:
            projections.markdown_read_notice(self.vault)
        finally:
            for kind in original:
                setattr(Path, kind, original[kind])
        self.assertEqual({k: v for k, v in counts.items() if v}, {},
                         f'okuma yolu vault gezinti yapıyor: {counts}')

    def test_okuma_uyarisı_temiz_vaultta_bos(self):
        self.assertEqual(projections.markdown_read_notice(self.vault), '')


class LegacyNameTest(unittest.TestCase):
    def test_eski_ad_henuz_calisiyor_mu(self):
        """Doktor hattı eski adı kullanıyor; iki adın da çalıştığı sabitlenir."""
        self.assertTrue(hasattr(projections, 'generated_markdown_health'))
        self.assertTrue(hasattr(projections, 'markdown_health'))


if __name__ == '__main__':
    unittest.main()