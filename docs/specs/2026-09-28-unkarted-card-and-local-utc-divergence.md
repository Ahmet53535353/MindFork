# Devir kartı sıralaması (tarihsiz kart) + günlük log/konsolidasyon saat ayrışmasının teste bağlanması

Tarih: 2026-09-28 · Durum: TAMAMLANDI · İlgili: `2026-09-28-upstream-merge-5.md`,
`2026-09-28-test-clock-fragility.md`

## Bağlam

`2026-09-28-upstream-merge-5.md` sonrası yapılan düzeltmelerin **patlama yarıçapı** denetimi
iki şey buldu: bir gerçek kusur ve bir bilinçli körleşme. Kullanıcı saat sabitlemesi için
(a) seçeneğini onayladı — sabitleme kalsın, ama bilinen ayrışma teste bağlansın.

## Bulgu 1 — tarihsiz devir kartı en eski sayılıyordu (gerçek kusur, bu dalın kendisi)

`clip_cards` kartları her kartın **kendi başlık tarihine** göre sıralıyordu
(`beyin_v3_companion.py`), ama sıralama anahtarı `stamp()`'in okuyabildiği tarihlerden kuruluyordu:

```python
def rank(item):
    index, card = item
    moment = stamp(card.splitlines()[0])
    return (moment is not None, moment or ('', ''), -index)     # okunamayan -> her zaman son
cards = [card for _, card in sorted(enumerate(cards), key=rank, reverse=True)]
```

Bir başlık tarih okunabilir değilse `moment` `None` olur ve anahtarın ilk bileşeni `False`
düşer; `reverse=True` ile o kart **listenin en sonuna** gider. Yani ajanın **en yeni kartının**
başlığı okunamaz biçimdeyse (`## Devir kartı`, yazım hatalı tarih), kart gerçekten daha eski
kartların **altına** düşüyor ve bağlamdan **düşürülebiliyor** — tarih sıralamanın önlemeye
çalıştığı arızanın aynısı, farklı bir girdiden.

Mevcut `test_undated_card_heading_does_not_displace_the_newest_dated_card` bu yönü **yakalamıyor**:
tarihsiz kartı dosyanın **sonuna** ekliyor, orada "en sona düş" kuralı zaten doğru sonucu veriyor.
Teşhis ölçüldü: yeni test (`## Devir kartı` + iki eski tarihli kart, 1200 ve 2000 bütçe) **önce
kırmızı** düştü ve bağlam `2026-09-27 10:32 · ORTA` kartını aldı; en üstteki yeni kart düştü ve
kesme bildirimi onu `"1 older handoff cards not shown"` diye **yaşlı** ilan etti.

### Çözüm: temkinli kural

Ne "tarihsizi en yeni say" ne de "en eski say" — ikisi de mevcut testi kırıyor. Kural:

> Sıralama **yalnız her başlık tarih okunabiliyorsa** tarihe göre yapılır; bir başlık okunamıyorsa
> **dosyanın kendi sırası** kullanılır.

Sıralamanın dayandığı şey tarih karşılaştırmasıdır; okunamayan bir başlık bu karşılaştırmayı
geçersiz kılar ve o noktada dosyanın sırası yazarın bilerek kullandığı tek sinyaldir
(`SKILL.md` devir kartlarında en yeninin üstte olmasını şart koşar).

Kabul edilen bedel: tarihsiz kart bulunan dosyalarda tarih sıralaması kaybolur, yani
"en yeni kart dosyanın sonuna eklenmiş" hatası bu karma dosyalarda geri gelebilir. Bu bilinçli
seçimdir — tarih sıralaması bir sezgi, tarihsiz kart belirsizlik; belirsizlikte kanıtlı davranış.

Mevcut beş teste karşı doğrulandı: tarihli dosyalar yeniden sıralanır, `## Previous` arşiv
başlığı zaten `handoff_cards` içinde elenir, tek kartlı legacy dosyada sıralama önemsizdir.

## Bulgu 2 — `TZ=UTC` sabitlemesi ürünün yerel tarih davranışını görünmez kılıyordu

`tests/conftest.py` tüm paketi UTC'ye sabitliyor (saat kırılganlığı düzeltmesi). Bu doğru bir
takas, ama bedeli ölçülmedi: **ürünün kendisinde iki farklı gün anlayışı var.**

| Yer | Gün nasıl türetiliyor |
|---|---|
| `beyin_v3_sessionlog.py:39-40` `_day(epoch)` = `datetime.fromtimestamp(epoch).date()` | **yerel** |
| `beyin_v3_dream.py:61-62` `_now()` = `.astimezone(dt.timezone.utc)` | **UTC** |

Doğrudan ölçüldü: `2026-09-28T21:30Z` damgası, `UTC-3` diliminde günlük log `2026-09-29`,
konsolidasyon penceresi `2026-09-28` veriyor. Yani Greenwich'in doğusundaki bir kullanıcı,
günün ilk saatlerinde **yarının** tarihli günlük log dosyasını alıyor ve iki özellik "bugün"
hakkında üç saat boyunca anlaşamıyor.

Bu ayrışma **hiçbir testle ölçülemiyordu**, çünkü paket UTC'ye sabitli ve UTC altında iki taraf
zaten tanım gereği aynı günü veriyor. Kullanıcının (a) seçimiyle bu kör nokta kayda geçirildi:
`tests/v3_local_utc_day_divergence_test.py` proses saat dilimini kendisi kaydırıp **üç olguyu**
birlikte sabitler:

1. konsolidasyon penceresi her dilimde UTC günü,
2. günlük log makineyi izler ve +03:00'te pencereden ayrışır,
3. UTC altında ikisi aynıdır — sabitlemenin ayrışmayı neden gizlediğinin kanıtı.

İleride biri ikisini aynı saate getirirse test kırmızıya döner ve **düzeltmenin ürüne ait olduğunu**
hatırlatır; saatin testte mi üründe mi düzeltileceğini bu dosya belirler.

Aynı sırada iki yan not da kayda geçti:

- `time.tzset()` **Windows'ta no-op**; bu sabitleme POSIX'e bağlıdır. Bugün zararsız çünkü
  `windows.yml` pytest koşturmuyor, ama pytest eklenirse koruma sessizce kaybolur — `conftest`
  docstring'ine yazıldı.
- `bridge.py:100` de `date.today()` ile yerel tarih kullanıyor; kökteki gün farkı oradan da
  geliyor.

## Bulgu 3 — gün seçimi artık hiçbir testle sabitlenmiyordu

Saat düzeltmesi iki testin tarihi `dt.date.today()` ile yeniden hesaplamak yerine ürünün
bildirdiği `report_path`'ten türetmesine çevirdi. Doğru takas, ama bir yanlılık bıraktı:
**ürünün hangi günü seçtiği** (plan günü mü uygulama günü mü) artık hiçbir testle bağlı değildi.
`dream.py:737` zaten `day = manifest['window']` kullandığı için bu tek satırlık sözleşme
teste alındı: raporun yazıldığı gün, `manifest.json`'un ilan ettiği `window` ile eşit olmalı
(`v3_dream_phase2_test.py`, `v3_human_use_month_test.py` q15).

## Ana dal karşılaştırması

Soruldu: bu sorun ana dalda var mı? Ölçüldü.

| Bulgu | `upstream/main` (da36d8c) | bizim `main` (f9a8b5f) | bu dal |
|---|---|---|---|
| Tarihsiz kart en eski sayılıyor | **yok** | yok | var (ve düzeltildi) |
| Yerel/UTC gün ayrışması | **yok** | yok | var (ölçülüp sabitlendi) |

`clip_cards`/`handoff_cards` ile `beyin_v3_sessionlog.py`/`beyin_v3_dream.py` upstream'de **hiç
yok**; ikisi de bu dalın eklediği kod. Yani ne ana dalı ne de yayımlanmış sürümü etkilemiş.
Ancak Bulgu 1'in **sınıfı** ana dalda gerçekten var: `excerpt`/`Journal.md` yolunda (`beyin_v3_companion.py:211-219`,
upstream ile birebir aynı) karışık dosyada `max(dated, ...)` yalnız tarihli girişleri gördüğü için
**tarihsiz en yeni giriş sessizce hiç seçilmiyor**. Hepsi tarihsizse davranış doğru (son giriş,
`:218`'in `if dated else` koruması). Upstream'e ayrı olarak bildirildi.

Bir düzeltme de bu denetim sırasında geri alındı: önce upstream'da `max()`'ın boş listede
çağrıldığını, yani Journal'da çökme olduğunu düşünmüştüm. Bu **yanlıştı**; satır 218'in sonu
`... [1] if dated else len(entries) - 1`. İddia kırpılmış çıktıdan (`cut -c1-98`) çıkarılmıştı ve
düzeltildi.

## Doğrulama

- Yeni kırmızı test, düzeltmeden önce: `AssertionError: 'HEAD_TARIHSSIZ' not found` (iki bütçede).
- `tests/v3_companion_multicard_test.py`: 10 test yeşil.
- Companion paketi: 69 yeşil.
- Bölünme testi: 3 yeşil (kendi saat diliminde ölçüyor, konuk saat diliminden bağımsız).
- `v3_dream_phase2_test.py`: 21 yeşil. `v3_human_use_month_test.py`: 17 yeşil.
- Tam paket: **933 passed, 1 skipped, 2307 subtests** (7 dk 50 sn) — 0 kırmızı.
  (930 → 934 toplanan: 1 multicard + 3 bölünme testi.)

## Kapsam dışı bırakılanlar (bilerek)

1. Kesme bildirimi `"older handoff cards"` diyor; dosya sırasıyla kesildiğinde "older" kesin
   değil. Mevcut test bu ifadeyi sabitliyor, ayrı iş kalemi.
2. Günlük logun da UTC'ye alınması **ürün davranışı değiştirir** (dosya adları değişir, günlük
   geçmiş okunabilirliği etkilenir) — ürün kararı, bu dalın test düzeltmesi değil.
3. `stamp()`'in yalnız `YYYY-MM-DD` okuması, Bulgu 1 ve upstream Journal kusurunun ortak kökü;
   ürünün yazdığı biçimler dışındaki başlıklar buraya takılıyor.
