# Mimari Temizlik Seti: Hibrit Sınır Kararı + FTS Sayacı + Sarmalayıcı Envanteri

Tarih: 2026-09-25 · Dal: feat/explicit-memory-typing · Durum: ONAYLANDI
Bağlam: M2 sonrası mimari değerlendirme (kullanıcı: "PR yok; sonradan eklenmiş gibi duran yerleri temizle").

## 1) Hibrit arama sınırı — KARAR: belgele, olduğu gibi bırak (#2)

Hibrit yığın (`records_fts` BM25 + RRF + `semantic_searcher` kancası) yalnız not düzeyi
`_retrieve` yolunda çalışır. Passage yolu (#83, tur-başı hook) bilinçli olarak **hafif sözel
blok yoludur**: 1 saniyelik kurulum bütçesi, df/FLOOR kalibrasyonunun tek-havuz varsayımı ve
JSON-türetilmiş-veri disiplini buna izin vermez; blok-FTS + arama-anı RRF entegrasyonu ayrı
bir Faz-5 işi olarak **ertelendi**. Tip kapıları her iki yolda da var (tek policy kaynağı).
Uygulama: PREFERENCES.md passage bölümüne karar maddesi + record'a "Kararlar" satırı.

## 2) Kök CLI `task_completion` sarmalayıcısı — inceleme sonucu: SİLİNECEK BİR ŞEY YOK (#3)

Blame: `scripts/beyin_v3.py:294-301` satırları upstream'in (1c0fd54e hknsahin97 + d324722
avenoxai). M1'de bizim bantımız görünüyordu; merge çözümünde upstream sürümü kazandı ve
M2'de `reader()` kök-neden düzeltmesi geldi. Sarmalayıcı artık upstream'in kendi doctor
konvansiyonudur (kardeşleri: `knowledge_freshness`, `validity` aynı desen) → yerinde kalır.
Uygulama: record'daki "kendi borcumuz" notunun düzeltilmesi ( blame kanıtıyla).

## 3) FTS rebuild bozuk-satır sayacı (#5)

Şimdi: rebuild döngüsü bozuk payload'ı **sessiz** atlıyor (ilke doğru, göz yok).
Tasarım (küçük, yüzeyi dar):
- Rebuild yalnız `fts_count == 0 && records_count > 0` iken koşar; döngü `skipped` sayar.
- `skipped > 0` ise `metadata('fts_malformed_skipped', str(n))` yazılır (temiz rebuild'te
  anahtar yazılmaz — yokluk = 0 demek, sürüm-öncesi DB'ler temiz kalır).
- Kök CLI doctor çıktısına bilgi amaçlı ek: `result['fts_malformed_skipped'] = int|0`
  (status sözleşmesi DEĞİŞMEZ — bozuk kayıt zaten retrieval/doctor kayıt yollarında görünür).
- Testler (önce kırmızı, `tests/custom/v3_fts5_test.py`):
  1. 1 bozuk + 2 sağlam payload rebuild'i → metadata `'1'`, sağlam iki kayıt indeksli.
  2. Temiz rebuild → anahtar yok.
  3. Mevcut bozuk-payload tolerans testi (açık FTS rebuild kolu) → anahtar `'1'`.

## Kapsam dışı

Passage hibritleme (Faz-5), upstream kaynaklı bayrak kokuları (`rejected_only`), Stop
hatırlatıcı yığını — kullanıcı kararıyla dokunulmuyor.

## Uygulama sonucu

- #2: PREFERENCES.md passage bölümüne karar maddesi + record'a "Karar — hibrit sınır" yazıldı.
- #3: blame envanteri record'a düzeltme olarak işlendi; kod değişikliği yok (sarmalayıcı upstream'in).
- #5: rebuild `skipped` sayacı + `metadata('fts_malformed_skipped')` (>0 iken) + kök CLI
  `result['fts_malformed_skipped']`; 2 yeni custom test (kırmızı→yeşil), hedefli 44/44.
