"""Bir receipt özeti kapanmayan bir çit içerirse indeks dosyaları okunmaz olur.

`_receipt_view_contents` (beyin_v3_projections.py) özeti `daily/v3/<gün>.md` ve
`knowledge/v3/outcomes.md` içine **kelimesi kelimesine** gömer. Markdown'da kapanmayan
``` bloğu, dosyanın kalanını kod bloğu sayar: Obsidian'da koyu arka plan, açık renk yazı.
`submit_receipt` özetin boş olup olmadığını ve refs'i denetler, içeriğin Markdown
olduğuna **bakmaz**; 2026-10-16'da vault'ta üç dosyanın (receipt + iki görüntü) bu
yüzden bozulduğu ölçüldü.

Düzeltme iki yerde olmalı: gömerken çitleri etkisizleştirmek (geçmişi de onarır) ve
gönderirken reddetmek (yenisini oluşmasını engeller). Ölçülmüş çözüm 4 boşluklu
girintili kod bloğu: projeksiyon girintiyi eklediğinde çit sayısı 3'e çıkar ve
Markdown girintili kod bloğu sayar — çit saymaz.
"""
import importlib.util
import json
import os
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('BEYIN_TEST_REPO', Path(__file__).resolve().parents[1]))
MODULE = ROOT / 'template/.claude/scripts/beyin_v3_sync.py'
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))
import beyin_v3_projections as projections


def load_module():
    spec = importlib.util.spec_from_file_location('beyin_v3_sync_fence_subject', MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    scripts = str(MODULE.parent)
    sys.path.insert(0, scripts)
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old
        sys.path.remove(scripts)
    return module


# 2026-10-16'da yazdigim receipt'in ozetinden: acilan ama kapanmayan blok.
BROKEN = ('AHMET BIR HATA GOSTERDI ve dogruydu. Temiz dosyanin sonunda su yaziyordu:\n'
          '\n'
          '  ```\n'
          '  > Kod eksik: ET, Path, gzip... (uyari)\n'
          '  Before using it with production data, ... (makalenin SON PARAGRAFI)\n'
          '\n'
          'Yani benim ekledigim uyari kod blogunun hemen arkasina gomuluyordu.')


def unclosed_fences(text):
    """Dosyada tek sayida kalan gercek çit satiri var mi? Gövde içindeki kod çitleri hariç."""
    inside = False
    depth = 0
    for line in text.split('\n'):
        stripped = line.strip()
        if not stripped.startswith('```'):
            continue
        if inside and stripped == '```':
            inside = False
            continue
        inside = not inside
        depth += 1
    return inside


class ReceiptSummaryFenceTest(unittest.TestCase):
    """Özet ne yazarsa yazsın, indeks dosyası okunur kalmalı."""

    def setUp(self):
        self.module = load_module()
        self.tmp = tempfile.TemporaryDirectory(prefix='beyin-fence-')
        self.addCleanup(self.tmp.cleanup)
        self.vault = Path(self.tmp.name) / 'Vault'
        self.vault.mkdir()
        self.engine = self.module.SyncEngine(self.vault, Path(self.tmp.name) / 'state')
        self.addCleanup(lambda: getattr(self.engine.store, 'close', lambda: None)())
        self.db = sqlite3.connect(self.engine.store.database)
        self.addCleanup(self.db.close)
        self.source = self.vault / 'notes/source.md'
        self.source.parent.mkdir(parents=True, exist_ok=True)
        self.source.write_text('---\n{"kind": "note", "visibility": "internal"}\n---\nKaynak.\n',
                               encoding='utf-8')

    def record(self, summary, ident='fence-probe'):
        """Receipt'i dogrudan tabloya yazar; gonderim ayrica test edilir."""
        with self.engine.store._connect() as db:
            db.execute('INSERT OR REPLACE INTO receipts VALUES (?,?)', (ident, json.dumps({
                'event_id': ident, 'summary': summary, 'refs': ['notes/source.md'],
                'harness': 'claude', 'created_at': '2026-10-16T12:00:00+00:00',
            })))
        return self.engine.sync()

    def submit(self, summary):
        return self.engine.store.submit_receipt(
            event_id='fence-submit', summary=summary,
            refs=['notes/source.md'], harness='claude')

    def test_kapanmayan_cit_ozet_indeksi_bozmaz(self):
        self.record(BROKEN)
        desired = projections._receipt_view_contents(self.engine, self.db, [])
        self.assertTrue(desired, 'görünüm üretilmedi; test ölçüm yapamaz')
        for name, content in desired.items():
            with self.subTest(view=name):
                self.assertFalse(unclosed_fences(content),
                                 f'{name} kapanmayan çitle bitiyor')

    def test_dengeli_cit_ozeti_aynen_kalir(self):
        """Dengeli çitler gömülebilir; sorun kapanmayanlarda."""
        balanced = 'Girdi:\n\n```\nkod satiri\n```\n\nDevam eden metin.'
        self.record(balanced)
        desired = projections._receipt_view_contents(self.engine, self.db, [])
        joined = '\n'.join(desired.values())
        self.assertIn('kod satiri', joined)
        self.assertFalse(unclosed_fences(joined))

    def test_duz_metim_ozeti_degismez(self):
        plain = 'Sadece duz bir iki cumle, hicbir kod yok.'
        self.record(plain)
        desired = projections._receipt_view_contents(self.engine, self.db, [])
        self.assertIn(plain, '\n'.join(desired.values()))

    def test_zehirlenmis_goruntuyu_sync_onar(self):
        """Onceden yazilmis bozuk goruntuyu, hash kaydi duruyorken de sync duzeltmeli.

        Gercek durum: 2026-10-16'da kapanmayan citli bir receipt iki goruntuyu bozdu.
        Receipt degistirilemedigi icin (amend yolu yok) tek yol projeksiyon katmani.
        """
        self.record(BROKEN)
        daily = self.vault / 'daily/v3/2026-10-16.md'
        outcomes = self.vault / 'knowledge/v3/outcomes.md'
        for path in (daily, outcomes):
            self.assertTrue(path.exists(), f'{path} uretilmedi')
        # eski davranis: govdeyi boz, hash kaydi oldugu gibi kalsin
        _hash, _atomic, render = self.engine.projection_helpers()
        broken = daily.read_text(encoding='utf-8').replace('\\\\`', '`')
        daily.write_text(broken, encoding='utf-8')
        outcomes.write_text(outcomes.read_text(encoding='utf-8').replace('\\\\`', '`'),
                            encoding='utf-8')
        with self.engine.store._connect() as db:
            for path in (daily, outcomes):
                rel = path.relative_to(self.vault).as_posix()
                db.execute('INSERT OR REPLACE INTO receipt_views VALUES (?,?)',
                           (rel, _hash(path.read_bytes())))

        self.engine.sync()
        for path in (daily, outcomes):
            with self.subTest(view=path.name):
                self.assertFalse(unclosed_fences(path.read_text(encoding='utf-8')),
                                 'sync zehirli goruntuyu onarmadi')

    def test_kacis_tek_ters_bolu_kullanir(self):
        BS = chr(96)   # backtick
        cift = chr(92) * 2 + BS      # cift kacis: ekranda gorunur kalir
        tek = chr(92) + BS            # dogru kacis
        out = projections.fence_safe_summary(BROKEN)
        fence_line = next(l for l in out.split('\n') if BS in l)
        self.assertNotIn(cift, fence_line, 'cift kacis var')
        self.assertIn(tek * 3, fence_line, 'tek kacis yok')
        self.assertNotIn(BS * 3, fence_line, 'kacislanmamis kaldi')


    def test_gonderim_kapanmayan_citi_reddeder(self):
        with self.assertRaises(ValueError):
            self.submit(BROKEN)

    def test_gonderim_dengeli_citi_kabul_eder(self):
        r = self.submit('Girdi:\n\n```\nkod\n```\n\nBitti.')
        self.assertTrue(r.get('event_id'))

    def test_gonderim_duz_metni_kabul_eder(self):
        r = self.submit('Duz metin, iyi hucre.')
        self.assertTrue(r.get('event_id'))


if __name__ == '__main__':
    unittest.main()


class FenceParityTest(unittest.TestCase):
    """CommonMark kurallari, 2026-10-17'de olculdu:

    Kapatabilmek icin cit acilistan kisа olmaz; girintili (4+ bosluk) kod blogu
    icindeki cit gercek degildir. Mevcut kod ikisini de yanlisliyordu: bir
    gercek bosluk (4-cit acik, 3-cit kapali -> koruma kaciyor) ve iki yanlis
    pozitif (ic ice citler, girintili kodda cit -> gecerli ozet REDDEDILIYOR).
    """

    BS = chr(96)

    def fence(self, n=3):
        return self.BS * n

    def assert_unbalanced(self, text, why):
        self.assertTrue(projections.unbalanced_fence(text), why)

    def assert_balanced(self, text, why):
        self.assertFalse(projections.unbalanced_fence(text), why)

    def test_kisa_cit_uzun_acilisi_kapatmaz(self):
        text = 'Metin:\n\n' + self.fence(4) + '\nkalici\n' + self.fence(3) + '\n\nDevam.'
        self.assert_unbalanced(text, 'acilis 4 backtick, kapanis 3: kapanmamis')

    def test_uzun_cit_kisa_acilisi_kapatabilir(self):
        text = 'Metin:\n\n' + self.fence(3) + '\nblok\n' + self.fence(4) + '\n\nDevam.'
        self.assert_balanced(text, 'kapanis acilistan kisа olmayabilir')

    def test_ic_ice_cit_dengeli(self):
        text = ('A:\n\n' + self.fence(4) + '\n' + self.fence(3) + '\n' + self.fence(4) +
                '\n\nB:\n\n' + self.fence(3) + '\n' + self.fence(3))
        self.assert_balanced(text, '4/3/4 ic ice ve ardindan 3/3 dengeli')

    def test_girintili_kod_blogundaki_cit_gercek_degildir(self):
        text = 'Metin:\n\n    ' + self.fence() + '\n    gercek kod\n\nDevam.'
        self.assert_balanced(text, '4 bosluk girintili kod blogu: cit yazidir')

    def test_bos_cit_satiri_hem_acilis_hem_kapanis(self):
        self.assert_unbalanced('Metin:\n\n' + self.fence() + '\nkod\n\nDevam.',
                               'bos bir cit satiri ici bosken ACILIS yapar')
        self.assert_balanced('Metin:\n\n' + self.fence() + '\nkod\n' + self.fence() + '\n\nDevam.',
                             'iki bos cit satiri: once acilir, sonra kapanir')

    def test_gonderim_gecerli_ozeti_reddetmemeli(self):
        """Gecersiz kabul edilen gecerli ozet bir regresyondur, gurultu degil."""
        gecerli = [
            ('ic ice dengeli', 'A:\n\n' + self.fence(4) + '\n' + self.fence(3) + '\n' + self.fence(4) + '\nB'),
            ('girintili kodda cit', 'Metin:\n\n    ' + self.fence() + '\n    kod'),
            ('uzun cit kapali', 'A:\n\n' + self.fence(3) + '\nx\n' + self.fence(4)),
        ]
        for ad, text in gecerli:
            with self.subTest(ad=ad):
                self.assertFalse(projections.unbalanced_fence(text), ad)

    def test_kacirma_yalniz_sizan_citlere_dokunmali(self):
        """Ic ice dengeli ozet oldugu gibi gecmeli; kacirma gereksiz degil."""
        text = 'A:\n\n' + self.fence(4) + '\n' + self.fence(3) + '\n' + self.fence(4) + '\nB'
        self.assertEqual(projections.fence_safe_summary(text), text)

    def test_kacirma_kapanmayan_citi_etkisizlestirir(self):
        text = 'Metin:\n\n' + self.fence(4) + '\nkalici\n' + self.fence(3) + '\n\nDevam.'
        out = projections.fence_safe_summary(text)
        self.assertNotEqual(out, text)
        self.assertFalse(projections.unbalanced_fence(out), 'kacirilan metin hala bozuk')
        self.assertIn('kalici', out, 'icerik korunmali')
        self.assertIn('Devam', out, 'icerik korunmali')


class ReceiptPathRejectionTest(unittest.TestCase):
    """Koruma, ajanların kullandığı GERÇEK yolda ölçülür.

    `beyin_v3_sync.py:receipt()` dosyayı önce yazıyor, sonra `sync()` ile DB'ye
    giriyor ve `store.submit_receipt` **en sonda** çağrılıyor. Denetim yanlış
    uçtaydı: ValueError yükseliyordu ama kayıt **yine de** diske ve DB'ye
    yazılmış oluyordu (sandbox'ta ölçüldü: DB 104 → 105, dosya oluştu). Bir kapı
    ki yeşil testle geçiyor ama geçmiyorsa kapı değildir.
    """

    def setUp(self):
        import shutil
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.vault = Path(self._tmp.name) / 'v'
        (self.vault / 'notes').mkdir(parents=True)
        self.state = Path(self._tmp.name) / 'state'
        self.note = self.vault / 'notes/kaynak.md'
        self.note.write_text('---\n{"kind": "note", "visibility": "internal"}\n---\nKaynak.\n', encoding='utf-8')
        module = load_module()
        self.engine = module.SyncEngine(self.vault, self.state)
        self.addCleanup(lambda: getattr(self.engine.store, 'close', lambda: None)())
        self.addCleanup(shutil.rmtree, self.vault, True)

    def db_event_ids(self):
        import json as _json
        db = self.state / 'memory.sqlite3'
        if not db.exists():
            return []
        conn = sqlite3.connect(db)
        try:
            return [_json.loads(row[0]).get('event_id')
                    for row in conn.execute('SELECT payload FROM receipts')]
        finally:
            conn.close()

    def test_kapanmayan_citli_ozet_hicbir_iz_birmemeli(self):
        f = FENCE = chr(96) * 3
        summary = f'Metin:\n\n{FENCE}\nkod satiri\n\nDevam eden metin.\n'
        with self.assertRaises(ValueError):
            self.engine.receipt('fence-yolu-001', summary, ['notes/kaynak.md'], 'claude')
        self.assertNotIn('fence-yolu-001', self.db_event_ids(), 'DB kaydi yazildi')
        receipts = self.vault / 'receipts'
        yazilan = [p.name for p in receipts.glob('*.md')] if receipts.is_dir() else []
        self.assertEqual(yazilan, [], 'receipt dosyasi yazildi: ' + str(yazilan))

    def test_gecerli_ozet_kaydedilmeli(self):
        """Red yolunu bir hata sanip gecersiz ozeti de engellemek kolay olurdu."""
        f = FENCE = chr(96) * 3
        summary = f'Metin:\n\n{FENCE}\nkod satiri\n{FENCE}\n\nDevam.\n'
        self.engine.receipt('fence-yolu-002', summary, ['notes/kaynak.md'], 'claude')
        self.assertIn('fence-yolu-002', self.db_event_ids())


class InfoStringRuleTest(unittest.TestCase):
    """CommonMark: bir backtick çitinin bilgi dizgisi backtick İÇEREMEZ.

    Vault taraması 2026-07-17'de buldu: bir bilgi notu çitlerden *bahsetmek* için
    şunu yazıyordu:

        ```` ``` ```` işaretleridir; işaretler ```` ````

    Satır satır başında 4 backtick ile başlıyor ve CommonMark'ta **çit değildir** —
    bilgi dizgisi backtick içerdiği için geçersizdir, düz metindir. Ölçüm koşum
    bunu açılış sayıp dosyayı bozuk işaretledi; aynı yanlış pozitif üretim
    kodundaki `unbalanced_fence`'de de vardı, yani kapı geçerli bir notu BLOCKER
    yapardı. Düz metinde çitten bahsetmek nadirdir ama tam olarak bu notun konusu.
    """

    BS = chr(96)

    def test_bilgi_dizgisinde_backtick_olan_cit_gecersizdir(self):
        satir = self.BS * 4 + ' ' + self.BS * 3 + ' işaretleridir; işaretler ' + self.BS * 4
        metin = 'Bir not:\n\n' + satir + '\n\nDevam metni.\n'
        self.assertFalse(projections.unbalanced_fence(metin), 'gecersiz bilgi dizgisi çit sayildi')

    def test_ciddi_bilgi_dizgisi_gecerli_cittir(self):
        metin = 'Bir not:\n\n' + self.BS * 3 + 'python\nkod = 1\n' + self.BS * 3 + '\n\nDevam.\n'
        self.assertFalse(projections.unbalanced_fence(metin), 'gecerli acik-kapali cit dengeli')

    def test_giris_dizgisinde_backtick_olan_satir_acilis_sayilmaz(self):
        """Bilgi dizgisi backtick içeren satır açılış değildir.

        İlk yazımda '``` `ek / kod / ```' belgesi 'dengeli' olmalıydı; yanlıştı.
        1. satır çit değil, 3. satır gerçek bir açılıştır ve kapanmaz — belge
        **dengesizdir**. Doğru ayrım şu: geçersiz sayılan satır bir *açılış*
        sayılmaz, ama ondan sonraki çapraz çift kapanmış kalır.
        """
        gecersiz = self.BS * 4 + ' ' + self.BS * 3 + ' işaretleridir'
        dengeli = gecersiz + '\n' + self.BS * 3 + '\n' + self.BS * 3
        self.assertFalse(projections.unbalanced_fence('Bir not:\n\n' + dengeli + '\n\nDevam.\n'),
                         'gecersiz aciis sayildi, sonraki capraz citler havada kaldi')
        kapanmamis = self.BS * 3 + '`ek\nkod\n' + self.BS * 3
        self.assertTrue(projections.unbalanced_fence('Bir not:\n\n' + kapanmamis + '\n\nDevam.\n'),
                        '3. satirdaki gecerli acilis kapanmadigi icin belgesi bozuk')
