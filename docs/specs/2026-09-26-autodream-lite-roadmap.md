# AutoDream-lite — konsolidasyon yol haritası (roadmap spec)

Tarih: 2026-09-26 · Durum: tasarım kararları alındı, uygulama sırada değil
İlgili kayıt: `docs/specs/2026-09-25-hybrid-rag-implementation-record.md` (Kalan işler #2)

## Amaç ve sınır

Vault'taki notların zamanla şişmesini **yazıyla** değil, mekanizmayla yönetmek:
bir konsolidasyon penceresinde (varsayılan haftalık, `beyin.py dream`) fazla/kopuk
/işe yaramaz notları Prune/Merge/Refresh ile toparlamak, dizini yeniden kurmak ve
boyut disiplini uygulamak. İlk sürüm **tek konsolidasyon modülü + bir komut** olsun;
zamanlayıcı/daemon yok (V3 ürün sınırı: modelsiz, bağımlılıksız, arka planda çalışan yok).

Kapsam dışı (kararlı): vektör indeksi, gom/graph, model çağrısı, chat içi otomatik
consolidation, "her aramada öğrenen" geri besleme döngüleri (§3 gerekçesi).

## 1. Boyut disiplini (ölçülebilir hedefler)

- Pencere girdisi: `knowledge/` + `notes/` ağacı; ölçüt: dosya sayısı ve toplam karakter.
- Eşikler (ilk sürüm, ölçümle ayarlanır): `>400` not veya `>150k` karakter → uyarı;
  tek dosya `>12k` karakter → Refresh adayı; 90 gündür hiç referans verilmemiş ve
  `status: draft` → Prune adayı (**yalnız aday listesi, silme otomatik değil**).
- Pencere çıktısı raporu: `daily/v3/` içine değil, `archive/auto-dream/<tarih>/report.md`
  (telemetri + geri alabilirlik).

## 2. Geri alınabilirlik: Prune/Merge öncesi ön-image zorunlu

Lite planından alınan ve *bu projede daha da sıkılaştırılmış* kural: damıtma
(Prune/Merge) geri döndürülemez yazmalardır; AutoDream penceresi başlamadan önce
**etkilenecek her dosyanın ön-image'ı** `archive/auto-dream/<tarih>/files/` altına
kopyalanır ve `manifest.json` (kaynak→yol, sha256) yazılır. `report.md` tek satırda
"geri al: `beyin.py dream --restore 2026-09-26`" yazar; `--restore` ön-imageı geri
yükler, dizini yeniden kurar. Reddedilen sürüm: "workbench kopyasını iki hafta tut"
(Lite Adım 5) — bizim mimaride masanın karşılığı `daily/log` blokları; asıl risk
notun kendisi, dolayısıyla kılıf not değil **snapshot** korunur.

## 3. Isı (kullanım sinyali) — pasif alıntı, sıcak yol yazmadan

Fikir kaynağı: Lite Adım 4 (`weight`/`last_touched` ısı haritası). Önerinin canlı
arama sırasında `weight += 1` yazması **reddedildi**: `context_for` sözleşmemiz
okuma-kalmadır (kilit sırası, tur başı 1 sn bütçesi, `harness parity` byte-eşitlik
testleri, maliyet); sıcak yola sayaç yazmak bu sözleşmeleri kırar.

Ölçeklenebilir gerçeklik: **sorgu günlüğü tablosu yok** (motor yalnız
`receipts(payload.refs)` ve `events` tutar; `query_log` diye bir şey mevcut değil).
Bu yüzden birincil ısı sinyali = **pasif alıntı frekansı**: her receipt'in `refs`
listesi vault-relative kaynak yollarıdır; AutoDream penceresi `receipts`'i
taramayıp `daily/v3/` projeksiyonundan (zaten receipt'ten üretilir) not başına
alıntı sayısı çıkarır, `created/updated` tarihleriyle birleştirir.

- Sıralama kuralı: alıntı = 0 olan notlar "soğuk"; alıntısı yüksek notlar Prune
  listesinden **dışarıda** kalır ve Merge hedefi olarak seçilmez.
- Sıralama AutoDream'ın kendi kararıdır; retrieval sıralamasına `weight` sokulmaz
  (arama sonucu determinizmi ve byte-eşitlik korunur).
- İsteğe bağlı, ilk ölçüm "pasif alıntı yetersiz" derse: sıcak yola **yazmadan**
  durum tarafında append-only `state/dream_hits.log` (O_APPEND, sqlite kilidi yok)
  ve pencerede okuma. Karar ölçüm sonrası, varsayılan: yapılmaz.

## 4. Ajanın rolü: kod iskelet, içerik ajan (V2 disiplini)

AutoDream bir Python fonksiyonu değil, bir iş akışıdır: modül aday listelerini
üretir, güvenli (yeniden yazılabilir) dosyalarda çalışır; **anlamlı birleştirme,
budama gerekçesi ve özet metni ajanın işidir** — V3'te bunun kanalı hazır:
`daily/log` oturum bloklarının `### Özet` bölümü (Beş başlık: Bağlam / Önemli
Konuşmalar / Alınan Kararlar / Öğrenilenler / Yapılacaklar) ve `beyin.py receipt`
olayları. "Masayı topla" komutu → `read` + ajan özeti + `receipt` + `last-session`
kartı; `daily/log` özeti zaten kalıcı kayda dönüşmüşse pencere yalnız
**tekrarları ve kalıntıları** temizler, yeniden özetlemez.

## 5. Aşama planı (her aşama TDD + tek geçişte tam paket)

1. **Ölçüm modülü** (salt-okunur): `beyin.py dream --dry-run` → envanter + aday
   listeleri (Prune/Merge/Refresh) + ısı tablosu; hiçbir şey yazmaz. Testler:
   deterministik çıktı, boş vault, tek dosya, restore edilebilirlik.
2. **Snapshot + Refresh**: ön-image kopyası, manifest, `--restore`; Refresh yalnız
   başlık/ayraç normalizasyonu ve frontmatter tazelemesi (idempotent).
3. **Merge**: yalnız alıntısı > 0 olan, birbirine bağlı notlar; her Merge snapshot'ın
   üstüne yazılır ve rapor satırı üretir.
4. **Prune**: **otomatik silme yok**; yalnız `status: draft` + 90 gün + alıntı 0
   adayları rapora düşer, kullanıcı `--apply` ile onaylar.
5. **Re-index + doctor**: snapshot'ın ardından dizin yeniden kurulur, `doctor`
   alanları (boyut, kopya sayısı, restore noktası) genişler.

## 6. Test ve kanıt disiplini

- Her komut için: kuru çalışma, snapshot/restore gidiş-dönüşü, idempotanslık,
  kilit sırası, hata ayrıklama (yarım pencere → restore edilebilir).
- Bir pencere çalıştıktan sonra `unittest` tam paket + canlı vault'ta ön/son
  `doctor` çıktısı kayda geçer (bugünkü E2E pratiğiyle aynı).
- Geri al kanıtı: `dream --restore` sonrası `sha256sum` kümesi pencere öncesiyle
  birebir aynı olmalı (test bunu assert eder).

## 7. Bilinçli ertelenenler

- Sıcak yol ısı geri beslemesi (write-amplification) — ölçüm gerekçesiyle.
- Çok kanallı/derin gömme araması (embedding sağlayıcısı gelmeden).
- Otomatik Prune (onay halkası olmadan silme) ve "öğrenen" otomatik ağırlıklar.
