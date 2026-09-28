# Takvim kırılganlığı: testler ürünün UTC gününü değil duvar saatini okuyordu (2026-09-28)

Tarih: 2026-09-28 · Durum: DÜZELTİLDİ · Kapsam: test altyapısı, ürün kodu değişmedi

## Belirti

Wiki işi push edildikten sonra tam paket yeşil değildi:

```
2 failed, 930 passed, 1 skipped, 2495 subtests
FAILED tests/custom/v3_dream_phase2_test.py::DreamPhase2Test::test_cli_apply_then_restore_round_trip
FAILED tests/custom/v3_human_use_month_test.py::HumanMonthE2ETest::test_q15_...
```

Her iki hata da aynı iddiada: `archive/auto-dream/<gün>/report.md` beklenen yolda değil. `wrote`
doğruymuş — yani konsolidasyon penceresi çalışmış, sadece rapor **başka bir güne** yazılmıştı.

## Teşhis (ölçüm, tahmin değil)

Ürün pencerenin gününü **UTC** ile kuruyor:

- `beyin_v3_dream.py:62` — `_now()` = `dt.datetime.now(dt.timezone.utc)`
- `beyin_v3_dream.py:737` — `day = manifest['window']`, yani gün **plan anında** sabitleniyor

Testler ise günü **yerel** saattan hesaplıyordu:

- `v3_dream_phase2_test.py:319` (öncesi) — `today = dt.date.today().isoformat()`
- `v3_human_use_month_test.py:925` (öncesi) — `today = dt.date.today().isoformat()`

UTC+3'te yerel gece yarısı ile UTC gece yarısı arasında (UTC 21:00–24:00, yani yerel 00:00–03:00)
günler **bir gün ayrışır**. 2026-09-27'de paket yeşildi; 2026-09-28 yerel gece yarısında başladığı
ve UTC hâlâ 27'si olduğu için iki test düştü. UTC de 28'e geçince yeniden yeşile döndü — yani
**her gün üç saatlik bir kırılma penceresi** vardı ve gün dönümü onu açmıştı.

### Deterministik yeniden üretim

Pencerenin varlığını ölçerek kanıtlandı:

```
TZ=Etc/GMT+12  →  testin gördüğü 2026-09-27, UTC 2026-09-28 (ayrışma)
                  test FAILS, tam olarak 331. satırda
TZ=UTC         →  ayrışma yok, test geçer
```

Ayrıca wiki öncesi noktada (`5cc5cab`, geçici worktree) iki test de düşüyordu: bulgu bu dalın
değil, saatin işiydi.

### İkinci, daha zayıf bulgu

`test_receipts_inside_window_are_referenced` **tek başına geçiyor**, tam pakette düşüyor. Bu
ayrı bir sıra bağımlılığı ve ayrı bir iş kalemi; bu kayıt onu sahiplenmiyor.

## Düzeltmeler

**1. Tasarım düzeltmesi (asıl olan):** testler tarihi yeniden hesaplamıyor, **ürünün bildirdiği
yolu** kullanıyor. `dream --apply` zaten `report_path` döndürüyor
(`beyin_v3_dream.py:753`), yani doğru sözleşme eldeydi:

- `tests/custom/v3_dream_phase2_test.py` — `today = dt.date.today()` kaldırıldı; iddia artık
  `self.vault / payload['report_path']` üzerinde, `--restore` günü bu yoldan türetiliyor.
  **Fixture'lar (`self.today = '2026-09-26'`, `self.moment`) bilerek değiştirilmedi** — dosyanın
  geri kalanı deterministik olmaya ve bu sabit tarihe dayanıyor.
- `tests/custom/v3_human_use_month_test.py` — `today = dt.date.today().isoformat()` kaldırıldı;
  rapor, manifest ve `--restore` günü `applied['report_path']` üzerinden türetiliyor.

**2. Saat sabitleme (sınıfı kapatmak için):** `tests/conftest.py` yeni; tüm paketi UTC'ye
sabziler (`os.environ['TZ'] = 'UTC'; time.tzset()`), böylece testlerin okuduğu gün ürünün okuduğu
günle aynı olur. `tests/v3_package_helpers.py` → `isolated_env()` de `'TZ': 'UTC'` taşır, çünkü
çağıranlar kendi ortamını bu sözlükten kuruyor ve aksi halde geliştiricinin saat dilimini
miras alırlardı.

## Doğrulama

- `TZ=Etc/GMT+12` altında **her iki test geçiyor** — düzeltmeden önce tam olarak burada
  düşüyorlardı. Sınıfın kapandığının kanıtı bu.
- `TZ=UTC` altında her iki test geçiyor.
- Tam paket: bkz. "Sonuç" bölümü.

## Ürün tarafında değişen bir şey yok

`day = manifest['window']` **korundu**: rapor planın gününe yazılır ve bu AutoDream'in
`--restore <gün>` sözleşmesiyle tutarlıdır. Değiştirilseydi geri alma imleci, günü vermeyen bir
uygulamaya dönüşürdü. Zaten testler artık ürünün tercihine göre okuyor; saatin hangi
anlayışta olduğu artık testin doğruluğunu etkilemiyor.

## Kalan sınıf (bu kayıt sahiplenmiyor)

1. `beyin_v3_sessionlog.py` günlük log için **yerel** tarih kullanırken `beyin_v3_dream.py` UTC
   kullanıyor. İkisi de doğru davranış olabilir ama aynı vault'ta iki gün anlayışı var; UTC
   21:00–24:00'te günlük log bir gün ileri görünür.
2. `test_receipts_inside_window_are_referenced` sıra bağımlılığı.
3. Testlerin geri kalanı hâlâ `dt.date.today()` okuyorsa, `conftest.py` UTC'ye sabitlediği için
   bugün güvenli; ancak sabit tarihli fixture'larla gerçek saati karıştıran başka testler varsa
   aynı sınıfa girer. Tarama yapılmadı.
