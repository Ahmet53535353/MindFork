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

## 0. Çalışma kapıları (gated execution)

`dream` bir "bakım penceresi" komutudur; tekrar tekrar çağrılabilir olduğu için
Anthropic'in AutoDream kapı modelinin işlevsel karşılığı uygulanır — **üç kapı**:

1. **24 saat kuralı:** son çalışma zamanı `metadata` anahtarında
   (`dream.last_run`); 24 saat geçmemişse komut "çok erken" deyip çıkar
   (`--force` yalnız teşhis için, rapora yazar).
2. **Kanıt kuralı (≥5 receipt):** son çalışmadan beri `receipts` tablosunda ≥5
   yeni kayıt olmalı. Neden receipt ve oturum değil: oturum sayacı `daily/log`
   bloğundan gelir, o özellik **opt-in ve varsayılan kapalı**; kapalı vault'ta
   oturum sayacı yok. `receipts` ise her vault'ta var. (Ölçüm öncesi önerilen
   (a) varyantı — hook'ta kalıcı oturum sayacı — ihtiyaç doğarsa ayrı iş.)
3. **Kilit:** `state/dream.lock` üzerinde `_portalock.exclusive`; kilit alınamazsa
   çıkış kodu ile vazgeçilir (ikinci konsolidasyon yarışmaz).

Kapılar `--dry-run` için de geçerlidir: ölçüm aracı da idisip lin uyurmaz
(Altın Kural: yeni kalıcı özellik ancak ölçümle; ölçümün kendisi bu komuttur).

Zamanlayıcı yok: paket daemon'laşmaz, ancak komut **idempotent ve kapılı**
olduğu için isteyen kullanıcı kendi `cron`/systemd timer'ıyla çağırabilir —
desteklenen senaryo, paketin kendi zamanlayıcısı değil.



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
`daily/log` oturum bloklarının `### Özet` bölümü (beş başlık: Bağlam / Önemli
Konuşmalar / Alınan Kararlar / Öğrenilenler / Yapılacaklar) ve `beyin.py receipt`
olayları. "Masayı topla" komutu → `read` + ajan özeti + `receipt` + `last-session`
kartı; `daily/log` özeti zaten kalıcı kayda dönüşmüşse pencere yalnız
**tekrarları ve kalıntıları** temizler, yeniden özetlemez.

**Muhakeme katmanı oturumdaki ajandır, ayrı bir model çağrısı değil.** Dış kaynak
(AutoDream) küratörü "fork edilmiş ayrı subagent" olarak tarif eder; bizim
karşılığımız zaten çalışan şey: vault'ta çalışan ajan (Claude/Codex/OpenCode…)
raporu okur, kararı ve gerekçeyi yazar, `--apply` onayı insanın. Başsız
"tam otomatik" bir küratör için `--llm` fazı **2026-09-26'da reddedildi**
(gerekçe §7).

## 5. Aşama planı (her aşama TDD + tek geçişte tam paket)

1. **Ölçüm modülü** (salt-okunur): `beyin.py dream --dry-run` → envanter + aday
   listeleri (Prune/Merge/Refresh) + ısı tablosu + **kapı raporu** (son çalışma,
   yeni receipt sayısı, kilit durumu); hiçbir şey yazmaz. Testler: deterministik
   çıktı, boş vault, tek dosya, kapı reddi (24 saat / <5 receipt / kilitli),
   restore edilebilirlik.
2. **Snapshot + Refresh**: ön-image kopyası, manifest, `--restore`; Refresh yalnız
   başlık/ayraç normalizasyonu, frontmatter tazelemesi ve **bağıl→mutlak tarih**
   normalizasyonu (idempotent) — dış kaynaktan alınan Refresh kuralı.
3. **Merge**: yalnız alıntısı > 0 olan, birbirine bağlı notlar; her Merge snapshot'ın
   üstüne yazılır ve rapor satırı üretir.
4. **Prune**: **otomatik silme yok**; yalnız `status: draft` + 90 gün + alıntı 0
   adayları rapora düşer, kullanıcı `--apply` ile onaylar.
5. **Re-index + doctor**: snapshot'ın ardından dizin yeniden kurulur, `doctor`
   alanları (boyut/taşma, kopya sayısı, restore noktası, son dream + kapı
   durumu) genişler.

## 6. Test ve kanıt disiplini

- Her komut için: kuru çalışma, snapshot/restore gidiş-dönüşü, idempotanslık,
  kilit sırası, hata ayrıklama (yarım pencere → restore edilebilir).
- Bir pencere çalıştıktan sonra `unittest` tam paket + canlı vault'ta ön/son
  `doctor` çıktısı kayda geçer (bugünkü E2E pratiğiyle aynı).
- Geri al kanıtı: `dream --restore` sonrası `sha256sum` kümesi pencere öncesiyle
  birebir aynı olmalı (test bunu assert eder).

## 7. Bilinçli ertelenenler / reddedilenler

- Sıcak yol ısı geri beslemesi (write-amplification) — ölçüm gerekçesiyle.
- Çok kanallı/derin gömme araması (embedding sağlayıcısı gelmeden).
- Otomatik Prune (onay halkası olmadan silme) ve "öğrenen" otomatik ağırlıklar.
- **`--llm` küratör fazı (2026-09-26'da reddedildi).** İki gerekçe birlikte:
  (1) kullanıcının çalıştırabileceği yerel model yok; (2) uzak API'ye vault
  içeriği göndermek ise "uzak servis çağrısı yok" ilkesini ihlal eder. Yerine
  kullanılan: oturumdaki ajan zaten bu muhakemenin güçlü tarafı (§4). İhtiyaç
  doğarsa (sürekli çalışan başsız bakım) yeniden açılabilir.
- KAIROS benzeri boşta-çalışan daemon: paket sınırı (§0 zamanlayıcı maddesi).

## 8. Dış kaynak: ne alındı, ne alınmadı (2026-09-26)

Dış desen: "Beyond the Session: Memory Engineering for Agent Teams" (Jordan
Carson, 2026-04-21) ve onun AutoDream/KAIROS anlatımı. **Kaynak uyarısı:**
AutoDream'in dört fazı ve üç kapısı, Anthropic'in *yayımlanmamış* KAIROS
daemon'una ilişkin **üçüncü-taraf sızıntı raporlarından gelir; birincil
doğrulama yok. Bu yüzden kayıt/PR metinlerinde "doğrulanmış ürün davranışı"
değil, **"ilham alınan dış desen"** olarak geçer.

Alınan ve zaten örtüşenler (konverjans, PR'da kullanılabilir): üç bellek boyutu
(bizde `VALID_MEMORY_TYPES = ("episodic","semantic","procedural")` ile birebir
aynı), pre-task hydration / post-task konsolidasyon ayrımı, aday belleğin
"terfi incelemesi" metaforu (bizim staging→sync + karantina hattımız), hybrid
BM25+vektör+RRF (Cloudflare'ın 5-kanallı RRF sonucu), boyut disiplini
(200 satır/25KB tavanı), tarih mutlaklaştırma (Refresh), 3 kapı + kilit.

Alınmayanlar: Redis/NATS koordinasyon katmanı, Temporal, bulut dosya deposu,
vektör DB bağımlılığı, organizasyon-geneli ikinci bellek katmanı — bunlar
çok-ajanlı/organizasyon ölçeğinin altyapısı; tek kullanıcılı yerel vault'ta
Altın Kural 3 (sıfır bağımlılık, modelsiz) ihlali olurdu.

## 9. Bu dönemde yazılacak kural ve doctor sözleşmeleri

Bunlar kod değil, sözleşmedir; aynı iş paketinde teslim edilir (A+F paketi dışında,
ayrı ve küçük TDD'li adımlar).

### 9.1 Doctor: `oversize` alanı (C)

`doctor` çıktısına tek alan: boyut tavanı aşan dosyalar. Denetim listesi mevcut
gerçek dosyalarla sınırlıdır (varsayım değil, doğrulanmış yüzey):
`knowledge/index.md`, `knowledge/log.md`, `knowledge/v3/outcomes.md`,
`daily/v3/<gün>.md` (projeksiyon), `Last-Session.md`, `Threads.md`, `Journal.md`
ve tekil notlar (>`12k` karakter → Refresh adayı). `Last-Session`/`Threads`
için tercih bütçeleri (`last-session-chars`, `threads-chars`) zaten var;
`oversize` bu bütçelerle aynı mantığı **tek alanda** toplar, yeni ayar
getirmez. Rapor satırı: dosya, karakter, tavan, sınırı aşan tekil not sayısı.

### 9.2 SKILL kuralı: bağıl tarih yazma (B)

Dış kaynaktaki Refresh kuralının en ucuz ve en günlük-dokunuşlu parçası:
notlarda **"dün", "geçen hafta", "bir süre önce" yazılmaz; mutlak tarih yazılır**
(`2026-09-26`). Refresh fazı bu metni deterministik olarak normalleştirir; kural
ajanın yazarken de doğru yapmasını sağlar. Kural SKILL.md'ye tek cümle olarak
eklenir (kalıcı özellik değil, davranış kuralı — Altın Kural'ın kapsamı dışında).

### 9.3 SKILL kuralı: iş-akışı tipi öğrenimi (D)

`procedural` tip bugün zaten geçerli ve görev akışında öneriliyor; eksik olan
**öğrenim yönlendirmesi**: `Öğrenilen:` beyanı bir *iş akışı/kural* tarif ediyorsa
(`"... şunu şöyle yap"`, "kural", "sıra", "kontrol listesi") `knowledge/concepts/`
notu `type: semantic` yerine **`type: procedural`** olmalı. Tip tanımının kaynağı
companion dosyasıdır (`🔮 850-Companion/memory-types.md`); kural o referansı
atıfla verir, tip listesi `MARKDOWN.md`'deki üçlüyle (`episodic|semantic|
procedural`) tutarlıdır.

## 10. Uygulama sırası ve Altın Kural ilişkisi

1. **A+F**: kapılar (§0) + `metadata` anahtarları + record'taki dış-doğrulama
   bölümü.
2. **C**: doctor `oversize` alanı.
3. **B+D**: SKILL.md kuralları (kod değişimi yok, test de gerektirmez).
4. Faz-1 `--dry-run` ölçüm modülü → **≥1 hafta gerçek kullanım ölçümü** →
   2-5. fazlar kararı (ölçüm geçmezse 2-5 yazılmaz).

Altın Kural'ın kapsamı burada netleşir: kural **sıcak yol (retrieval/hook)
değişikliklerini** bağlar; kullanıcı çağrılı pencere komutları ve skill kuralları
ölçümün kendisini üretir, dolayısıyla kapı dışındadır.
