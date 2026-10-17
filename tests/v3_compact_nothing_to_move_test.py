"""Compact'in iki ölçülen kusuru: "taşınmadı" ile "sana kaldı" aynı durum kodu,
ve taşınmadığında da tam yedeğin arşive yazılması.

2026-10-17 ölçümü (gerçek vault): `Threads.md` için `needs_rewrite` döndü; aynı
dosyanın tam yedeği arşive **8 kez** yazılmıştı (beyan edilen toplam 84.867
karakter, arşiv dosyası 94.031 karakter).

Algoritma (`plan`): `##` seviyesi Threads.md'de **container** sayılır
(`CONTAINER['Threads.md'] == 3`), bu yüzden taşınabilir olanlar içlerindeki
tarihli bloklardır. Tarih, iki noktadan **önce** geliyorsa satır "alan" sayılır
ve taşınmaz. En yeni tarihli blok her zaman korunur; sınır hâlâ aşıksa en eski
bloklar taşınır. **Taşınacak hiçbir şey kalmazsa** plan `None` döner ve durum
`needs_rewrite` olur — kullanıcıya "elle yaz" işi yüklenir, oysa taşınacak bir
şey yoktur. O yolda dosya yine de arşive tam olarak kopyalanır.

Fixture notu: sınır altındaki dosyada compact hiçbir şey yapmaz, testler boşuna
yeşile döner. Bu yüzden dosya her zaman sınırın üstünde kurulur
(`write_threads` bunu doğrular) ve "aday yok" ile "aday var" durumları ayrı
kurulur.
"""
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(os.environ.get('BEYIN_TEST_REPO', Path(__file__).resolve().parents[1]))
MODULE = ROOT / 'template/.claude/scripts/beyin_v3_compact.py'
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))

POINTER = 'Arşivlenen metin'


def load_compact():
    spec = importlib.util.spec_from_file_location('beyin_v3_compact_subject', MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = old
    return module


def bullets(prefix, count, start=0):
    return '\n'.join(f'- {prefix} {i}.' for i in range(start, start + count))


# Taşınacak aday YOK: sınırın üstünde ama tek tarihli blok var, o da en yeni.
NOTHING_TO_MOVE = (
    '# Threads.md\n\n## Active Threads\n\n'
    '## yeni acik is (2026-10-16)\n\n'
    + bullets('acik is maddesi', 40) + '\n\n'
    + '#### tek tarihli blok (2026-10-01)\n\n'
    + bullets('tek blok maddesi', 10) + '\n\n'
    + "## Kapalı thread'ler\n\nArşivlenen metin: `.../Arşiv/Threads-2026-10.md`\n\n"
    + '## Closed Threads\n')

# Taşınacak aday VAR: iki tarihli blok; en eskisi taşınır, en yenisi korunur.
SOMETHING_TO_MOVE = (
    '# Threads.md\n\n## Active Threads\n\n'
    '## eski is kapandi (2026-10-02)\n\n'
    + bullets('eski madde', 18) + '\n\n'
    + '#### daha eski is (2026-09-20)\n\n'
    + bullets('eski kayit', 30) + '\n\n'
    + '#### daha yeni ama yine eski (2026-10-01)\n\n'
    + bullets('orta kayit', 5) + '\n\n'
    + '## yeni acik is (2026-10-16)\n\n'
    + bullets('yeni madde', 14) + '\n\n'
    + "## Kapalı thread'ler\n\nArşivlenen metin: `.../Arşiv/Threads-2026-10.md`\n\n"
    + '## Closed Threads\n')


class CompactBase(unittest.TestCase):
    LIMIT = 1000

    def setUp(self):
        self.compact = load_compact()
        self._tmp = tempfile.TemporaryDirectory(prefix='beyin-compact-')
        self.addCleanup(self._tmp.cleanup)
        self.vault = Path(self._tmp.name) / 'Vault'
        self.state = Path(self._tmp.name) / 'state'
        self.state.mkdir(parents=True)
        self.vault.mkdir()
        self.threads = self.vault / '🔮 850-Companion/Threads.md'
        self.threads.parent.mkdir(parents=True, exist_ok=True)
        self.sessions = self.vault / '🔮 850-Companion/Last-Session.md'
        self.sessions.write_text('# Last-Session.md\n\n## 2026-10-10 09:00 · eski · abc\n\nEski kart.\n',
                                 encoding='utf-8')
        import beyin_v3_companion as companion
        companion.save_limits(self.state, {'Threads.md': self.LIMIT, 'Last-Session.md': 3000})
        self.assertTrue(companion.read_limits(self.state)[1], 'limits fixture gecerli olmali')

    def write_threads(self, text):
        self.threads.write_text(text, encoding='utf-8')
        self.assertGreater(len(text), self.LIMIT,
                           f'fixture sinirin altinda ({len(text)} <= {self.LIMIT}); test bosuna gecer')

    def archive_text(self):
        path = self.threads.parent / 'Arşiv' / 'Threads-2026-10.md'
        return path.read_text(encoding='utf-8') if path.exists() else ''

    def run_compact(self):
        return self.compact.compact(self.vault, self.state)


class NothingToMoveTest(CompactBase):
    """Tasınacak aday yokken ölçülen davranış.

    Buradaki iki iddia **çürütüldü** ve testler çürütme sonrasına göre yazıldı:

    * "Her çalıştırma tam yedek yazıyor, arşivi şişiriyor" — **yanlış**. Kod
      `backup='exists'` ile aynı metni atıyor; sandbox'ta ölçüldü: 1. çalıştırma
      +6.222 karakter, 2. ve 3. çalıştırma **değiştirmedi**. Arşivdeki 8 yedeğin
      8'i farklı boyut bildiriyor, yani 8 farklı dosya durumu.
    * "`needs_rewrite` kullanıcıya yazma işi yüklüyor, oysa taşınacak şey yok" —
      kısmen doğru ama **kasıtlı sözleşme**: `reason` alanı ve `beyin_entry`
      çıktısı ("taşınacak tarihli eski kayıt yok") zaten ayrımı söylüyor, ve dört
      mevcut test bu adı bilerek sabitliyor. Durum adı kusur değil, sadeleştirme
      isteği olurdu; ölçülmüş bir kusur göstermedikçe değiştirilmedi.

    Kalan gerçek ve değerli: taşınan metin kaybolmaz, en yeni blok korunur,
    güvenlik yedeği aynı durumda tekrarlanmaz. Bunlar regresyon nöbetçisi.
    """

    def setUp(self):
        super().setUp()
        self.write_threads(NOTHING_TO_MOVE)

    def test_guvenlik_yedegi_bir_kez_yazilmali(self):
        self.run_compact()
        tek = len(self.archive_text())
        self.assertGreater(tek, 0, 'guvenlik yedegi hic yazilmadi')
        self.run_compact()
        self.assertEqual(len(self.archive_text()), tek, 'ayni durumda arsive tekrar yazildi')
        self.run_compact()
        self.assertEqual(len(self.archive_text()), tek, 'ucuncu calistirma da buyuttu')

    def test_tasinmadiysa_dosya_yerinde_kalmali(self):
        self.run_compact()
        canli = self.threads.read_text(encoding='utf-8')
        self.assertIn('yeni acik is', canli, 'aktif thread kaldirilmis olurdu')
        self.assertGreater(len(canli), self.LIMIT, 'dosya sinir altina indirilmis olamaz')

    def test_tasinacak_yoksa_durum_ve_gerekce_saydam_olmali(self):
        result = self.run_compact()
        rapor = (result.get('files') or {}).get('Threads.md') or {}
        self.assertEqual(rapor.get('status'), 'needs_rewrite')
        gerekce = str(rapor.get('reason', '')).lower()
        self.assertTrue('older dated entry' in gerekce or 'no dated entry' in gerekce,
                        f'kullaniciya "neden tasinamadi" sebebi soylenmeli: {rapor.get("reason")!r}')
        self.assertEqual(rapor.get('moved_chars', 0), 0, 'hicbir sey tasinmadi demesi')


class RealMoveTest(CompactBase):
    def setUp(self):
        super().setUp()
        self.write_threads(SOMETHING_TO_MOVE)

    def test_tasinan_metin_arsivde_kelimesi_kelimesine_durmalı(self):
        self.run_compact()
        arsiv = self.archive_text()
        self.assertTrue(arsiv, 'tasa bir sey tasinmadi')
        self.assertIn('daha eski is', arsiv, 'tasan metin arsivde bulunamadi')
        self.assertIn('eski kayit 0.', arsiv, 'tasan metin kelimesi kelimesine durmali')

    def test_en_yeni_blok_korumali(self):
        self.run_compact()
        canli = self.threads.read_text(encoding='utf-8')
        self.assertIn('yeni acik is', canli, 'en yeni blok korunmali')
        self.assertNotIn('yeni acik is', self.archive_text(), 'en yeni blok arsive tasinmis olurdu')
        self.assertIn('daha yeni ama yine eski', canli, 'korunan tarihli blok kalmali')

    def test_tasindiktan_sonra_dosya_sinir_in_altinda(self):
        # Genel durum 'needs_rewrite' olabilir: ayni kod "tasinacak yok" ve
        # "hasi limit ustunde" anlamlarini tasiyor. Burada dosya seviyesi konusulur.
        result = self.run_compact()
        rapor = (result.get('files') or {}).get('Threads.md') or {}
        self.assertEqual(rapor.get('status'), 'compacted', 'dosya tasinmadi')
        self.assertTrue(rapor.get('within_limit_after'), 'sinir hala asili')
        self.assertLessEqual(len(self.threads.read_text(encoding='utf-8')), self.LIMIT)


if __name__ == '__main__':
    unittest.main()
