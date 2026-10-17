"""Üretilmiş Markdown bozuksa kimse öğrenmiyor: 2026-10-16'da iki indeks dosyası
kapanmayan çit yüzünden okunmaz hale geldi ve hiçbir katman bunu bildirmedi.

Bu kapı yalnız **üretilmiş** görüntüleri denetler (`daily/v3/`, `knowledge/v3/outcomes.md`),
çünkü onlar `sync` ile yeniden yazılabilir. `receipts/*.md` **değişmezdir**: oradaki
kapanmayan çit kalıcıdır ve hiçbir komutla düzeltilemez; bu yüzden kapı onu
bilgi olarak listeler ama `doctor` durumunu yükseltmez — aksi hâlde doktor kalıcı
olarak kırmızı kalır ve çıkışı olmayan bir alarm olur.
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


class GeneratedMarkdownHealthTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / 'daily/v3').mkdir(parents=True)
        (self.vault / 'knowledge/v3').mkdir(parents=True)
        (self.vault / 'receipts').mkdir()
        self.addCleanup(self._tmp.cleanup)

    def write(self, relative, text):
        path = self.vault / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def test_temiz_kasa_ok_doner(self):
        self.write('daily/v3/2026-01-01.md', BALANCED)
        self.write('knowledge/v3/outcomes.md', BALANCED)
        report = projections.generated_markdown_health(self.vault)
        self.assertEqual(report['status'], 'ok')
        self.assertEqual(report['broken'], [])

    def test_bozuk_uretilmis_goruntu_kapiyi_kaldirir(self):
        self.write('daily/v3/2026-01-01.md', UNBALANCED)
        report = projections.generated_markdown_health(self.vault)
        self.assertEqual(report['status'], 'broken')
        self.assertEqual([b['source'] for b in report['broken']], ['daily/v3/2026-01-01.md'])
        self.assertEqual(report['broken'][0]['line'], 3)

    def test_outcomes_da_denetlenir(self):
        self.write('knowledge/v3/outcomes.md', UNBALANCED)
        report = projections.generated_markdown_health(self.vault)
        self.assertEqual(report['status'], 'broken')
        self.assertIn('knowledge/v3/outcomes.md', [b['source'] for b in report['broken']])

    def test_degismez_receipt_alarm_yaratmaz(self):
        self.write('receipts/abc.md', UNBALANCED)
        self.write('daily/v3/2026-01-01.md', BALANCED)
        report = projections.generated_markdown_health(self.vault)
        self.assertEqual(report['status'], 'ok', 'degismez kayit doktoru surekli kirmiziya cevirir')
        self.assertEqual(len(report['immutable_receipts']), 1)
        self.assertEqual(report['immutable_receipts'][0]['source'], 'receipts/abc.md')

    def test_uretilmemis_dosyalar_taranmaz(self):
        self.write('notes/el-notu.md', UNBALANCED)
        self.write('okuma/ham/kirpik.md', UNBALANCED)
        report = projections.generated_markdown_health(self.vault)
        self.assertEqual(report['status'], 'ok', 'kapi yalniz uretilmis goruntuleri denetler')

    def test_icerik_dil_dondurmez(self):
        self.write('daily/v3/2026-01-01.md', UNBALANCED)
        projections.generated_markdown_health(self.vault)
        self.assertEqual((self.vault / 'daily/v3/2026-01-01.md').read_text(encoding='utf-8'),
                         UNBALANCED, 'kapi yalniz okur, hicbir seyi yazmaz')

    def test_eksik_dizin_çökmemeli(self):
        import shutil
        shutil.rmtree(self.vault / 'knowledge/v3')
        report = projections.generated_markdown_health(self.vault)
        self.assertIn(report['status'], ('ok', 'broken'))


if __name__ == '__main__':
    unittest.main()
