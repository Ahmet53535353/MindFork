"""Returning after a break is a continuity question: companion context must come back (#151)."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'template/.claude/scripts'))
from beyin_v3_companion import fold, relevant


class ReturningQueryTest(unittest.TestCase):
    def test_reported_return_sentences_are_continuity_queries(self):
        for query in (
            'bir haftalık tatilden döndük, neler yapmıştık',
            'bir haftalik tatilden donduk, neler yapmistik',
            'neredeydik',
            'kaldığımız yer neresi',
            'son durum ne',
            'ne olmuştu',
            'neler yaptık',
            'what did we do',
            'catch me up',
            'hatirlat bana nerede kaldik',
            'Tatilden döndüm, özet geç',
            'Son durumumuz nedir?',
            'What did we work on yesterday?',
            'where were we?',
        ):
            with self.subTest(query=query):
                self.assertTrue(relevant(query))

    def test_missing_turkish_letters_and_upper_case_do_not_hide_a_query(self):
        for query in ('kisiligim', 'kişiligim', 'NEREDEYDİK', 'KALDIĞIMIZ YER', 'NELER YAPMIŞTIK'):
            with self.subTest(query=query):
                self.assertTrue(relevant(query))

    def test_the_existing_forms_still_match(self):
        for query in ('ne yaptık', 'son oturum', 'nerede kaldık', 'where did we leave', 'kişiliğim'):
            with self.subTest(query=query):
                self.assertTrue(relevant(query))

    def test_third_person_and_ordinary_questions_stay_out(self):
        for query in (
            'Kargonun son durumu ne?',
            'Siparişin son durumu nedir',
            'Bu fonksiyon ne yapıyor?',
            'Neden olmuştu bu hata, logu aç',
            'Ne yapalım?',
            'kişi listesi',
            'Make a catchy title',
            'what does this do',
            'where is the config',
            "Python'da liste nasıl sıralanır?",
        ):
            with self.subTest(query=query):
                self.assertFalse(relevant(query))

    def test_fold_keeps_turkish_words_readable(self):
        self.assertEqual(fold('İSTANBUL Şifre Müşteri Arşiv ığdır â'), 'istanbul sifre musteri arsiv igdir a')


if __name__ == '__main__':
    unittest.main()
