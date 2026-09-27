# AutoDream faz 3 — Merge: BULGU 8'in kapatılması ve ajan planı (2026-09-26)

Tarih: 2026-09-26 · Durum: ONAYLANDI, uygulanıyor
Yol haritası: `docs/specs/2026-09-26-autodream-lite-roadmap.md` (§5 adım 3, §4, §5.1)
Faz-2 planı: `docs/specs/2026-09-26-autodream-phase2-snapshot-refresh-plan.md`
Dal: `feat/memory-consolidation`

## Neden bu faz önce

Bir aylık insan kullanımı E2E'si bir P0 buldu: `_merge_pairs`
(`dream.py:172-193`) bir adayı **çözülmüş saymıyor**. Kullanıcı iki ödeme notunu
birleştirip birini işaretçiye çevirdiğinde, eşleşme yeniden çıkıyordu — çünkü
aday yalnız `_title()` üzerinden bakıyor ve küme testi bir **alt-küme** karşılaştırması
(`first_tokens <= second_tokens`). Aynı başlığı taşıyan bir işaretçi not, birleşmiş
notun başlığının alt kümesidir; dolayısıyla aday kalıcıdır. Aday çözülmüş sayılsa
bile, kullanıcının onayı yanlış nota bağlanabilir.

Faz-3 bu yüzden önce **BULGU 8'i** kapatıyor, sonra merge'in yazma yüzeyini açıyor.

## Kararlar

### 1. `--apply` gövdeyi yazmaz; ajan planı yazar

Roadmap §4 ilkesi içerik kararının oturumdaki ajanda olduğunu söyler ve faz-2'de
Refresh için aynı kararı verdik: **kod yalnız makineye ait olanı yazar.** Merge'de
makineye ait olan şey çiftin kendisi ve kurtarma kopyasıdır; birleşen **metin**
insan cümlesidir (hangi not geçerli, sıralama, çelişki çözümü).

Bu yüzden `dream --apply`:
- çiftlerin **kaynaklarını snapshot'lar** (faz-2 makinesi),
- `archive/auto-dream/<tarih>/merge-plan.md` yazar: her çift için iki kaynak, hedef
  not, ortak token'lar ve ajana talimat,
- **hiçbir notun gövdesine dokunmaz**.

Gövdeyi kodun birleştirmesi (tek başlık altında birleştirip diğerini stub'a
çevirmesi) seçeneği değerlendirildi ve **reddedildi**: sıralama ve "hangi başlık
geçerli" kararlarını ajanın muhakemesinden alıp koda taşır, §4'ü bayatlatır.

### 2. Aday eşleşmesi: başlık alt-kümesi **veya** gövde örtüşmesi

Mevcut başlık davranışı korunur (regresyon testleriyle), üstüne gövde görüşü gelir:
gövde token'ları `beyin_v3._tokens` ile alınır — yani **retrieval ile aynı
gövdeleme**, böylece aday ile arama aynı dili konuşur. Kaynak: heading yolu +
gövdenin ilk `BODY_TOKENS_CHARS` karakteri.

Eşikler muhafazakâr ve sabitlerde: en az `MIN_BODY_SHARED` (3) ortak token **ve**
küçük kümenin en az `MIN_BODY_RATIO` (%50) kadarı. Aynı konuda farklı başlıklı iki
not kaçırılmaz; farklı konuda iki not yanlış eşleşmez (negatif test zorunlu).

### 3. İşaretçi (stub) otomatik çözümleme

Bir not, kendisinden uzun olan hedefin **vault-göreli yolunu** anıyorsa artık
işaretçidir ve adaydan düşer. Yanlış susturmayı önleyen koşul: işaretçi, hedefin
karakterinin en fazla `STUB_MAX_RATIO` (%40)'ı kadar olmalıdır. Gerçek bir not diğerini
"anarak" uzun bir cümle kurabilir; gerçek bir stub kısadır. Bu oran olmadan kural
iki gerçek notu da susturabilirdi.

### 4. Kalıcı dismiss listesi

`archive/auto-dream/dismissed.json` = `{"schema": 1, "pairs": [[a, b], ...],
"notes": [...]}`. `dream --dismiss <a> <b>` bir çifti, `dream --dismiss <yol>` o
notu içeren tüm çiftleri kaydeder.

**Depo vault içinde.** Bu bir içerik kararıdır (bu iki not birleşmesin); `state/`
reinstall'da kaybolur, vault senkronlanır. Not ağacının dışında olduğu için indekslenmez.

**Bozuk dosya pencereyi durdurmaz:** doğrulanır, kullanılamıyorsa bir uyarıyla geçilir
(upstream'in `.beyin-exclusions.json` yaklaşımıyla aynı). Bir pencere, geçersiz bir
dismiss dosyası yüzünden hiç çalışmamalıdır.

## Filigran ve `wrote`

`wrote`, pencerenin bir artefakt üretmesidir: ya bir Refresh değişikliği ya da bir
merge planı. Adaylar çözülene kadar sonraki haftalık pencerede tekrar raporlanır —
bu bir hata değil, ajanın henüz yapmadığı işin hatırlatmasıdır. Çözüldüğünde (işaretçi
tespiti veya dismiss) aday bir daha çıkmaz.

## Test planı (TDD, kırmızıdan başla)

`tests/custom/v3_dream_phase3_test.py`:

1. gövde benzerliği, başlıkları farklı iki notu aday yapar
2. başlık alt-kümesi davranışı korunur (regresyon)
3. farklı konuda iki not eşleşmez (yanlış pozitif yok)
4. **işaretçi önerilmez** (BULGU 8'in kalbi)
5. hedef yolunu anmayan kısa not **önerilir** (aşırı susturma yok)
6. %40'ın üzerindeki kısa not işaretçi sayılmaz
7. dismiss edilen çift bir daha önerilmez
8. dismiss kalıcıdır (yeni store/pencere sonrası da sessiz)
9. `--dismiss` tek yol formu o notu içeren tüm çiftleri susturur
10. bozuk dismiss dosyası pencereyi durdurmaz
11. `--apply` iki notu da snapshot'lar ve **gövdeye dokunmaz**
12. restore iki notu da bayt bayt döndürür
13. CLI: `--dismiss` ve `--apply` gidiş-dönüşü; plan dosyası hedefi ve token'ları listeler

**Artı:** ay sürücüsüne q16 — E2E'nin iki ödeme notunu ajan birleştirip **aynı
başlığı taşıyan bir işaretçi** bırakıyor, sonraki `dream` artık önermemeli. Bulduğumuz
hata teste dönüşüyor. Test izsiz kalmalı (q15'teki gibi geri alma).

## Sıra

1. Bu spec.
2. Kırmızı testler.
3. Kod: eşleşme, stub tespiti, dismiss, merge planı, CLI.
4. Hedefli yeşil → tam paket yeşil → sürücü q16.
5. Doküman: roadmap §5 adım 3 ve §5.2, record Kalan işler #2, PREFERENCES.
6. Commit + push.

## Riskler

- **Gövde kuralı yanlış pozitif üretebilir.** Eşikler muhafazakâr; negatif test
  (farklı konuda iki not) zorunlu kılındı.
- **Stub tespiri gerçek notları susturabilirdi.** `%40` kuralı olmadan kural iki
  gerçek notu da sustururdu; eşik sabit ve testli.
- **Geçersiz dismiss dosyası pencereyi kilitlememeli** — doğrulanır, uyarılır, geçilir.
- `wrote` artık bir plan dosyası için de doğru olmalı; yanlış hesaplanırsa filigran
  ya gereksizce ilerler ya hiç ilerlemez. Her iki yön de testli.

## Uygulama sonucu

Dal: `feat/memory-consolidation`. TDD: 15 senaryo önce yazıldı ve eksik kod yüzünden
kırmızı doğrulandı. Tam paket **875/875** yeşil (skipped=1).

- `beyin_v3_dream.py`: `_body_tokens`, `_overlap`, `_points_at`, `_is_pointer`,
  `_kind`, `_pair_key`, `_dismissed_keys`, `dismissed`, `dismiss`, `_merge_target`,
  `_write_merge_plan`, `_write_window_file`. Sabitler: `BODY_TOKENS_CHARS=600`,
  `MIN_BODY_SHARED=3`, `MIN_BODY_RATIO=0.5`, `STUB_MAX_RATIO=0.4`,
  `DISMISSED_PATH`, `MERGE_PLAN`.
- `beyin_v3_sync.py`: `EXCLUDED_DIRS`'a `'archive'`.
- CLI: `dream --dismiss <SOURCE>...`.
- Ay sürücüsü: **q16** — gerçek kurulumda iki ödeme notu aday çıkıyor, ajan
  birleştirip **aynı başlığı taşıyan işaretçi** bırakıyor, aday düşüyor. BULGU 8
  canlı olarak kapandı.

### Yol üstünde bulunan dört gerçek hata

1. **Kurtarma kiti hafızaya karışıyordu (en ciddisi).** `--apply` sonrası CLI bir
   `sync` çalıştırır ve `archive/` dizini indeksleniyordu: her ön-image bir "not"
   oluyor ve **kaynak notun kendisiyle** eşleşiyordu
   (`['odeme-yontemi.md', 'odeme-yontemi.md']`). Bu yalnızca CLI yolunda görünürdü,
   birim testler `sync()` çağırmadığı için kaçıyordu. `EXCLUDED_DIRS`'a `'archive'`
   eklendi ve "snapshot hiçbir zaman not olmaz" diye bir regresyon testi yazıldı.
2. **Hayalet aday.** `_merge_pairs` kayıtlardan çalışıyordu; diskte **olmayan** bir
   notun kaydı kaldığında (konsolidasyon notu sildikten sonra) çift üretiliyordu —
   ajanın taşıyamayacağı bir öneri. Artık adayın **iki dosyası da diskte olmalı**.
3. **Gövde kuralı tür sınırını geçiyordu.** İçerik benzerliği her yerde benzerlik
   bulur: gerçek kurulumda bir **notu bir görevle** eşleştirdi
   (`odeme-yontemi.md` ↔ `tasks/odeme-sayfasi.md`). Birleştirme bir iddiyi
   birleştirir, görevi değil. Aynı `kind` şartı eklendi.
4. **Kendi kendine çift.** Aynı kaynağın iki kaydı (yeniden indeks) birbirini aday
   gösterebiliyordu.

### Test tarafında bulunan üç sessiz hata

- **`pairs()` sıra duyarsızdı.** Kaynaklar sıralı döndüğü için `(a, b)` ile `(b, a)`
  karşılaştırması **trivially** yeşildi: "işaretçi önerilmiyor" testi, aslında
  "öneriliyor" bir durumu yeşil gösteriyordu. `frozenset` ile sırasızlaştırıldı.
- **Fixture'lar gerçekçi değildi.** Birleştirilmiş not 200 karakterlikti; o zaman
  95 karakterlik bir işaretçi gerçekçi bir not gibi görünüyor ve %40 kuralı onu
  doğru olarak susturmuyordu. Notlar gerçek uzunluğa getirildi — kural yanlış değil,
  ölçüm çerçevesiydi.
- **Faz-1'in iki merge testi kayıtları dosyasız tohumluyordu.** "Dosya şartı"
  kuralı onları eledi; fixture'lar gerçekçi hale getirildi (dosya + kayıt).

### Yeni bulgu, faz-3'ün kararı değil (ölçüldü, kayda geçti)

**Bir işaretçi not, birleştirilmiş notu aramada geçersiz kılabiliyor.** Sürücüde
konsolidasyon "yinelenen notu sil" yerine "işaretçi bırak" biçiminde denendi
(better practice: kaynak bağlantıları çözülü kalır) ve `odeme icin ne karar
vermistik` sorusunda arama **85 karakterlik işaretçiyi** 378 karakterlik gerçek
notun önüne geçirdi — kısa notun az kelimesi yüksek ağırlık alıyor. Bu, retrieval
sözleşmesine yeni bir madde demek (işaretçi işareti ve kapı), faz-3'ün kapsamı
değil ve sürücü bu yüzden **orijinal davranışında** tutuldu (yinelenen not silinir,
`knowledge/concepts/odeme-yontemi-ek.md`). Kayda geçirildi; sıradaki iş kalemi.
