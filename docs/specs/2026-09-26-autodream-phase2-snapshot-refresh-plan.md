# AutoDream faz 2 — Snapshot + Refresh + `--restore` (uygulama planı, 2026-09-26)

Tarih: 2026-09-26 · Durum: ONAYLANDI, uygulanıyor
Yol haritası: `docs/specs/2026-09-26-autodream-lite-roadmap.md` (faz 1 tamam, faz 2-5 bekliyor)
Dal: `feat/memory-consolidation` · Taban: `a97e308`

## Neden şimdi

Roadmap §10 gereği faz 1'in ardından "**≥1 hafta gerçek kullanım ölçümü**" şartı
vardı ve "ölçüm geçmezse 2-5 yazılmaz" deniyordu. Bu şart artık yerine geldi:
`tests/custom/v3_human_use_month_test.py` (30 sanal gün, 13 oturum, gerçek
installer + CLI + hook) faz-1 çıktısının gerçekte ne ürettiğini ölçtü.

Ölçülen:

- **24 saat + ≥5 receipt kapıları ikisi de gerçekten reddetti** (G21: 0 yeni
  receipt, <24 saat) — kapılar teorik değil, çalışıyor.
- **Prune adayı**: 120 gündür alıntısız `status: draft` not rapora düştü.
- **Merge adayı**: yinelenen not rapora düştü.
- **Refresh adayı**: 12 000 karakter sınırını geçen not (`NOTE_CAP_CHARS`) rapora düştü.
- Uygulama insani elle yapıldı ve **yalnız beklenen dosya** değişti; rapor
  dışında hiçbir dosyaya dokunulmadı.

Yani aday üretimi ve kapı disiplini ölçüldü. Kalan belirsizlik mutasyonun
güvenliği: geri alınabilirlik. Faz 2 tam olarak o eksik parça.

## Faz 2 kapsamı

Roadmap §5 adım 2 ve §2 (geri alınabilirlik):

1. `dream --apply`: kapıları **uygular** (yalnız bildirmez), kilidi alır, her
   etkilenecek dosyanın **ön-image'ını** kopyalar, `manifest.json` (sha256) yazar,
   Refresh'i uygular, dizini yeniden kurar, `report.md` yazar ve filigranı tüketir.
2. `dream --restore <tarih>`: manifest'i doğrular ve ön-image'ları geri yükler.

`dream` (bayraksız) **değişmez**: salt-okunur rapor.

## Refresh'in kesin sözleşmesi (karar)

Roadmap §5 "bağıl→mutlak tarih normalizasyonu" der. Uygulama sırasında iki sorun
görüldü ve kapsam bilinçli daraltıldı:

- **Anchor belirsizliği**: "dün" hangi güne göre çözülecek? Notun `updated` tarihi
  mi, komutun çalıştığı gün mü? Sessiz tahmin, kullanıcının yazdığı cümleyi
  yanlış tarihe çevirir.
- **Yetki**: §4 ilkesi içerik kararının oturumdaki ajanda olduğunu söylüyor
  ("ağacı yerinde düzelt, eski kartı alta ekleme"). Kodun insan cümlesini
  yeniden yazması bu ilkeyi bayatlatır.

**Deterministik yazan (kod, idempotent):**
- başlık/ayraç normalizasyonu
- frontmatter tarih alanları — **yalnız notun kendi `updated`/`created` tarihi
  çözülebilirse**; çözülemezse tahmin edilmez, rapora düşer
- `updated` tazelemesi — **yalnız gövde gerçekten değiştiyse**. Aksi halde
  `updated_at` geri çekilir ve not arama sıralamasında "yeni" görünür (sessiz bir
  sıralama bozulması).

**Yalnız raporlayan (ajanın metni):**
- gövdedeki bağıl tarih ifadeleri → `prose_dates: [{path, line, phrase}]`,
  Türkçe diakritik katlamasıyla (companion'daki `_fold` deseni).

Bu, SKILL'e eklenen "mutlak tarih yaz" kuralını (B) **ölçülebilir** kılar: kural
ajanı yazarken doğru yapmaya zorlar, pencere ihlalleri raporlar, döngü kapanır.

**Roadmap §5 de bu kararla güncellenir** (dış desenden bilinçli sapma, gerekçesiyle).

## Emniyet özellikleri

- `archive/auto-dream/<tarih>/` not ağaçlarının (`knowledge`, `notes`) **dışında**:
  snapshot kopyaları kendi aday listelerine giremez (test assert eder).
- **Geri al kanıtı** (§6): `restore` sonrası sha256 kümesi pencere öncesiyle
  **birebir aynı**; test bunu assert eder.
- Manifest sha256'sı tutmuyorsa `restore` **reddeder**, sessizce bozuk geri yükleme yapmaz.
- Filigran **yalnız gerçekten bir şey yazıldığında** tüketilir; 0 değişiklikte
  "kapalı" kalır (yoksa haftalık ölçüm kendi penceresini kapatır — §0'daki hata).
- Yazılan notlar `companion-compact` handler'ındaki gibi yeniden sync edilir.
- `--apply` kilidi **oluşturur** (faz-1'in `_locked` yalnızca okur ve dosya yoksa
  kilit tutulamaz kabul eder).

## Test planı (TDD, kırmızıdan başla)

Yeni `tests/custom/v3_dream_phase2_test.py`:

1. `snapshot_manifest_sha256` — ön-image + manifest içerik hash'i tutuyor
2. `restore_birebir_pre_window_bytes` — §6 kanıtı
3. `apply_idempotent` — ikinci `--apply` değişiklik yapmıyor
4. `apply_refuses_inside_gate` — kapı kapalıyken **arşiv dizni bile** oluşmuyor
5. `second_window_loses_lock_race` — kilitliyken ikinci pencere vazgeçiyor
6. `crash_after_snapshot_still_restores` — yarım pencere kurtarılabilir
7. `apply_consumes_watermark_only_when_it_wrote` — 0 değişiklikte filigran durur
8. `restore_rejects_edited_manifest` — sha uyuşmazlığı reddedilir
9. `refresh_never_touches_generated_projections` — `is_generated` koruması
10. `prose_dates_are_reported_not_rewritten` — gövde değişmeden raporlanır
11. CLI `--apply` / `--restore` gidiş-dönüşü

**Artı:** ay sürücüsüne (`v3_human_use_month_test.py`) apply→restore senaryosu —
geri al kanıtı gerçek kurulumda ölçülür, yalnız birim testte kalmaz.

## Belge borcu (bu işle birlikte)

- **§0 kapı-2 gerekçesi eski**: "oturum sayacı `daily/log` bloğundan gelir, o
  özellik opt-in ve varsayılan kapalı" → günlük log artık **varsayılan açık**
  (`1b053cc`). Alternatif "(a) hook'ta kalıcı oturum sayacı" yeniden
  değerlendirilebilir olarak işaretlenir; bu fazda receipt kapısı korunur.
- **BULGU 8 → faz-3 ön koşulu**: merge adayı `dream.py:172-193`'te yalnız `title`
  token'larına bakıyor ve "çözüldü" durumu tutulmuyor. Faz 3 Merge'e başlamadan
  önce kalıcı dismiss listesi + gövde benzerliği yazılmalı; yoksa bu turda
  yaşadığımız "aday kaybolmuyor" davranışı mutasyona döner.

## Sıra

1. Belge borcu + bu spec.
2. Kırmızı testler.
3. Kod (`snapshot`/`normalize`/`apply_refresh`/`restore`/`_acquire`, `--apply`, `--restore`).
4. Hedefli yeşil → tam paket yeşil → ay sürücüsü apply+restore.
5. Doküman: roadmap §11 faz-2 sonucu, record Kalan işler #2, PREFERENCES/RUNTIME bayrak yüzeyi.
6. Commit + push.

## Riskler

- **Yazan bir komut.** `--apply` ilk kez gerçekten dosya değiştirecek; geri al
  yolu testlerle kanıtlanmadan ilerlenmez (snapshot/restore round-trip kırmızı
  testleri önce yazılır).
- **Sıralama bozulması**: `updated` dokunuşu yanlış yere düşerse not aramada
  öne geçer; yalnız gerçekten değişen içerikte dokunma kuralı bunu kapatır.
- **Snapshot'un aday listesine girmesi**: `archive/` ağaç dışında ama test
  kilitleyici.
- Manifest/raprot yazımı kısmi kalırsa pencere kurtarılamaz → kriz anında
  `restore`; test 6 bunu doğrudan sınar.

## Uygulama sonucu

Dal: `feat/memory-consolidation`. TDD ile teslim edildi: önce 21 senaryo yazıldı
ve eksik kod yüzünden kırmızı doğrulandı, sonra kod geldi.

- `beyin_v3_dream.py`: `snapshot`, `restore`, `normalize`, `prose_dates`,
  `apply_refresh`, `_acquire`, `_gate_blockers`, `window`, `_write_report`.
  Sabitler: `ARCHIVE_ROOT='archive/auto-dream'`, `MANIFEST='manifest.json'`.
- CLI: `dream --apply` / `dream --restore <tarih>` / `--force`. `dream` bayraksız
  **değişmedi**: faz-1 sözü (rapor hiçbir koşulda kilit dosyası oluşturmaz) ayrı
  testle korunuyor.
- Test: 21 yeni senaryo + ay sürücüsüne gerçek kurulumda apply→restore kanıtı.
  Tam paket **859/859** yeşil (skipped=1).

**Yol üstünde bulunan ve düzeltilen dört gerçek hata** — hepsi kendi testimin
kırmızısıyla yakalandı:

1. **Kilidi ters veriyordu.** `_acquire` `yield not acquired` ile "kilit bende"
   durumunu "başkasında" diye bildiriyordu; her `--apply` kendi kilidini
   "başkası almış" sanıp vazgeçiyordu. Test `a_locked_state_refuses_a_second_window`
   ve `watermark_moves_after_a_window_that_changed_a_note` bunu birlikte yakaladı.
2. **Frontmatter değişikliği raporlanıyordu ama yazılmıyordu.** `normalize`
   tarihi çözüp `changes` listesine yazıyor, döndürdüğü metinde ise gövde
   kalıyordu: rapor yalan söylüyordu. Ayrıca alan değişimi kapatıcı `---`'den önceki
   satır sonunu yutuyordu (`{json}# Başlık`). Fence `(open, raw, close)` olarak
   yeniden kuruldu ve yalnız **değişen alan** yerinde yazılıyor (anahtar sırası ve
   biçim bozulmuyor).
3. **Rapor katlanmış metni gösteriyordu.** `prose_dates` "geçen hafta" yerine
   "gecen hafta" döndürüyordu; ajanın okuyacağı raporda kullanıcının kendi
   yazımı olmalı. `_fold` karakter başına uzunluk koruduğu için span doğrudan
   özgün satıra taşındı (bu, ayrıca ölçülerek doğrulandı).
4. **`updated` tazelemesi sıralamayı bozardı.** İlk tasarımda pencere, gövdesi
   değişmeyen notun `updated` alanını da ilerletiyordu; 400 taze notu
   aramada öne atacaktı. Kural netleştirildi: `updated` **yalnız** gövde gerçekten
   değiştiyse ilerler.

**Test verisinde bulunan iki sessiz hata** (kod doğruydu, test yanlış ölçüyordu):
- Üç fixture notu 12 000 karakterlik aday tavanının **altındaydı**; biri
  "idempotans" testi olduğu için **trivially** geçiyordu. Bu sınıf hatayı bir daha
  yakalayamamak için `assert_refresh_candidate()` yardımcısı eklendi: artık tavanın
  altındaki fixture testi sessizce anlamını yitirmiyor.
- CLI testi sabit tarih beklerken komut gerçek saati kullanıyordu.

**Ölçüm şartı karşılandı.** §10'un "≥1 hafta gerçek kullanım ölçümü" şartını
30 sanal günlük ay sürücüsü doldurdu: iki kapı da gerçekten reddetti, üç aday
türü de (Prune/Merge/Refresh) rapora düştü ve uygulama insani elle yapıldığında
yalnız beklenen dosya değişti. Böylece faz 3-5'in ön koşulu yerine geldi; kalan iş
mutasyonun geri alınabilirliğiydi, o da bu fazda kanıtlandı.

**Yarıda kalan iş:** faz 3 Merge, §5'e göre BULGU 8'i (başlık tabanlı aday eşleşmesi
ve kalıcı "çözüldü" durumu) ön koşul olarak bekler.
