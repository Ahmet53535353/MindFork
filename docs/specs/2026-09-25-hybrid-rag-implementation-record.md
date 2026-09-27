# Hibrit RAG & Tip Bazlı Getirme — Uygulama Kaydı (2026-09-25)

## Tamamlanan commit'ler (origin/feat/explicit-memory-typing)

| Commit | İçerik |
|---|---|
| 1fbbcb1 | Tasarım spesifikasyonu (docs/specs/) |
| 14f382a | TDD uygulama planı (docs/plans/) |
| 7d452a4 | Aşama 1: VALID_MEMORY_TYPES doğrulaması + retrieve(types=...) filtresi |
| b100ddc | Aşama 2: records_fts (FTS5/BM25) tablosu, ingest/update senkronu, eski DB rebuild |
| cda8eb4 | Oturum dokümanları |
| e2f3850 | Aşama 3: _rrf_fuse + semantic_searcher kancası; FTS stopword filtresi; dense-rank |
| f863410 | Companion ends() bütçe-dolum düzeltmesi |
| 96558c0 | Bu uygulama kaydı |
| ca12d39 | Otomatik tip sezgisi tasarım spesifikasyonu |
| 8ad567e | Otomatik tip sezgisi: infer_types + _retrieve bağlama (yumuşak kapı); tests/custom/__init__.py ile discovery düzeltmesi |
| dce12f0 | Upstream merge planı |
| 3ceb8e9 | Upstream merge: avenoxai/avenoxbeyin main (61 commit) |
| 73b2e3f | Merge sonuç kaydı (spec) |

## Teknik kararlar

- Tip filtresi: types=None (tümü) / str / list; geçersiz tipte ValueError; geriye dönük uyumlu.
- FTS5: unicode61 remove_diacritics 2; ingest/update BEGIN IMMEDIATE içinde records_fts ile atomik.
- FTS sorgusu durak kelimeleri içermez (gürültü aday patlamasını önler).
- Dense rank: eşit BM25 skorları aynı sırayı alır → stabil sıra (güncellik sonra id) bozulmaz.
- RRF: k=60; vektör motoru yokken saf BM25 sırası korunur; semantic_searcher callable iken füzyon.
- Companion ends(): satır sınırı kırpmanın bıraktığı boşluk ortadan kapanışa doğru geri doldurulur; suyla-doldurulmuş bütçe çöpe gitmez.
- Otomatik tip sezgisi: muhafazakâr Türkçe ipucu listeleri; tek küme eşleşmesinde filtre, şüphede (0 veya ≥2) filtresiz; açık `types` her zaman kazanır; **yumuşak kapı** — sezgisel filtre tip alanı olmayan kayıtlara asla dokunmaz, katı filtre yalnız açık `types` ile.
- Merge çözümleri: `_validate` birleşimi (type + inference validity); `_eligible` refactorü kazanır, tip kapıları yeni `_retrieve`'a port edildi; sync `allowed` kümesi birleşimi.
- Type zorunluluğu gevşetildi: note_create/task_create'ta `type` artık **varsa geçerli olmalı** (upstream'in tipsiz not/task akışlarıyla uyum; memory-types.md güncellendi).
- FTS rebuild toleransı: türetilmiş veri asıl veriyi açılmaktan alıkoyamaz — kurucudaki rebuild döngüsü bozuk payload'ı atlar, doktorun bozuk-indeks sözleşmesi korunur (testle kilitli).
- FTS bozuk-satır sayacı: rebuild `metadata('fts_malformed_skipped')` yazıyor (yalnız >0), kök CLI doctor `fts_malformed_skipped` alanında bilgi olarak gösteriyor; status sözleşmesi değişmedi.
- **Karar — hibrit sınır:** hibrit yığın (BM25 + RRF + semantik kanca) yalnız not yolunda; passage yolu bilinçli hafif sözel blok yolu, Faz-5 ertelendi. Gerekçe: tur-başı 1 sn kurulum bütçesi + tek-havuz df/FLOOR kalibrasyonu. Ayrıntı: `docs/specs/2026-09-25-hybrid-boundary-and-fts-counter-design.md`.
- **Düzeltme (blame envanteri):** kök CLI'deki `task_completion` try/except sarmalayıcısı bizim M1 bantımız değil, upstream'in kendi düzeltmesi (1c0fd54e + d324722 `reader()`); M1 merge'ünde upstream sürümü kazanmış. Silinecek bir borç yok.

## Test durumu

- Aşama sonu kilometre taşları: 466/466 → tip sezgisi + discovery düzeltmesiyle 493/493.
- **Upstream merge sonrası: 673/673 yeşil** (`python3 -m unittest discover tests -p "*test.py"`; upstream'in ~200 yeni testi dahil). skipped=1 platform-bağımlılığı DEĞİL, upstream'in kendi koşullu testi: `v3_task_completion_test` kanıt-refs varyant testi yalnız case-insensitive hacimlerde koşar, Linux'ta kendisini atlar.
- **Passage tip kapısı sonrası: 681/681 yeşil** (+7: `v3_passage_types_test`).
- **İkinci upstream merge (M2, `a136a2a`, upstream `f9a8b5f`): 725/725 yeşil** — reddedilen
  çıkarım olgunlaştırma, görev sözleşmesi sertleştirme, bilgi tazeliği #109; plan + sonuç
  `docs/specs/2026-09-25-upstream-merge-2-plan.md`.
- **Mimari temizlik seti (hibrit sınır kararı + FTS sayacı): 727/727 yeşil** (+2 sayaç testi);
  `docs/specs/2026-09-25-hybrid-boundary-and-fts-counter-design.md`.
- **İnceleme sertleştirme seti (harici review, 6 madde): 734/734 yeşil** (+7 test) — supersedes savunması,
  `types=[]` ValueError, strict-yol FTS atlama, sessiz-düşüş sayaçları
  (`fts_query_errors`/`semantic_search_errors` + doctor), sıralama-semantiği pin testleri,
  memory-types.md çelişki düzeltmesi; `docs/specs/2026-09-25-review-hardening-design.md`.
- **FTS↔Sync yazma omurgası (P0 düzeltme, 2. inceleme): 738/738 yeşil** (+4) — sync artık
  records_fts'i aynı transaction'da günceller; `FTS_PARAMS` imzasıyla drift'li DB'ler
  kendini onarır; doctor `fts_consistency`; tip sabiti tek kaynak; context_for fail-fast;
  `docs/specs/2026-09-25-fts-sync-spine-design.md`.
- Custom testler `tests/custom/` içinde (`__init__.py` sayesinde kök discover artık dahil ediyor):
  - `v3_memory_types_test.py` — tip doğrulama ve filtreleme
  - `v3_fts5_test.py` — FTS5 şema, senkron, rebuild, tam sembol araması, bozuk payload toleransı
  - `v3_rrf_hybrid_test.py` — RRF matematiği ve semantik kanca
  - `v3_companion_ends_fill_test.py` — iki uçlu kırpma bütçe dolumu
  - `v3_type_inference_test.py` — ipucu birim testleri, yumuşak kapı, override, entegrasyon
  - `v3_passage_types_test.py` — passage yolunda tip kapıları: yumuşak/açık filtre, override, cache-değişmezliği, ValueError sırası
 
## Canlı vault E2E doğrulaması (2026-09-25)

Unit Paket'in dışında, taze bir vault (`/tmp/beyin-e2e-vault`, 2 proje / 7 kaynak) üzerinde
yalnız gerçek CLI + salt-okunur store API ile çatala özel tüm işlevler uçtan uca denendi:

| Alan | Komut/yöntem | Sonuç |
|---|---|---|
| Doctor yeni alanları | `doctor` | `fts_consistency {records,indexed,orphans}` + sayaçlar + `fts_malformed_skipped` yayında ✓ |
| Tip boru hattı | seed + `task-update` + db okuması | tipli dosyalar tipli; tipsiz → `type:null` (gevşek sözleşme: yumuşak kapıda kalır, açık filtrede dışlanır); update'te tip kalıcı ✓ |
| Rev-çakışması / history | `task-update` ×2, `history` | yanlış revision → `RevisionConflict`; history sıralı snapshot'lar ✓ |
| **P0 spine (canlı)** | dosya düzenle→`context`; dosya sil→`sync`→`doctor` | yeni token sync'li sorguda ANINDA bulunur, `--no-sync` snapshot'ında yoktur; silmede `orphans:0`, FTS hit'i kalktı, delete event ✓ |
| İpucu sezimi | store API | "hatırla/geçen hafta"→episodic, "nasılırım/adım adım"→procedural, "tanimi neydi"→semantic ✓ |
| Tip kapıları | store API | `[episodic]`→yalnız episodic; tip-None kayıt açık filtrede dışlanıyor; ipucu kapısı yumuşak; `types=[]`/bozuk tip → ValueError ✓ |
| Proje izolasyonu | store API | bravo oturumunda alpha sorgusu → boş ✓ |
| Passage yolu | strict context | gerçek bütçede blok+citation üretir; küçük bütçe ve eşleşmeyen sorguda **bilinçli abstain**; `types=[episodic]` passage'te de uygulanıyor; hook yolu `strict=True` ile production'da canlı ✓ |
| note-create CLI | JSON metadata `type` | dosya üretildi, sync'te `type:semantic` korundu ✓ |

**Bulgular:**
1. *CLI yüzey boşluğu (düşük öncelik):* kök CLI `context` `--types`/`--strict` bayrağı
   sunmuyor ve `--file` beyaz listesi `types` alanını reddediyor. Production hook yolu
   `strict=True`'yu kendi geçer, `types` API'den kullanılabilir; belge (`SKILL.md`) CLI'de
   `--types` önermiyor — çelişki yok. İstenirse yarım saatlik ek: bayraklar + beyaz liste.
2. Test gözlemi: passage katmanı çok küçük `budget_chars`'ta bilinçli abstain ediyor —
   tasarım gereği (halüsinasyon yerine boş); dokümanda vurgulanabilir.

## Canlı vault E2E — genel/upstream işlevler (2026-09-25)

Üçüncü bir taze vault (`/tmp/beyin-general-vault`) üzerinde çatal özelliklerinden bağımsız
16 senaryoluk upstream işlev koşucusu: **16/16 PASS**.

| Grup | Senaryo → sonuç |
|---|---|
| Temel | sync(4) · doctor · context+citation · eşleşmeyen sorguda abstain ✓ |
| Yazma API | task-create · geçersiz kaynak yolunun reddi · receipt **idempotency** (aynı event_id → tek `receipts/` dosyası) · history ✓ |
| Ayarlar | preferences yaz/ok (context_chars/mode) · secret-filter: `AKIA…` → `[REDACTED]`, ham anahtar DB'de YOK, doctor sayacı 2 ✓ |
| Companion | compact dry-run + gerçek koşu — limitler dahilinde doğru no-op, hiçbir girdi kaybı yok ✓ |
| Bütünlük | **duplicate id karantinası** (`all copies quarantined`, temizlik sonrası succeeded) · done-görev → `legacy_done=1` (#92 sözleşmesi: sözleşmesiz eski görev suçlanmaz) · olay/gap sayacı ✓ |
| Skill | skill-import → `.claude/skills/denama` + skill-sync + doctor temiz ✓ |

Kod değişikliği gerekmedi; upstream yüzeyi çatalda davranış koruyarak çalışıyor.

## Belge tazeliği denetimi (2026-09-25)

Dal dokümanları baştan tarandı; bayat olan dört nokta giderildi, kod değişmedi:
`RUNTIME.md` retrieval paragrafları artık FTS5/BM25 türetilmiş dizinini (yazma
omurgası bakımı + imza-self-heal + yeni sıralama sözleşmesi + `types=` + üç doctor
alanı) anlatıyordu; `MARKDOWN.md`'ye şema kaynağı olarak **"Optional memory type"**
bölümü eklendi; `PREFERENCES.md` sıralama maddesine `fts_consistency` yarım cümlesi;
README'nin "yerel kelime eşleştirmesi" cümlesi çatalın gerçek arama mimarisine
(BM25 + tipli hafıza + pasaj blokları + semantik kanca hazırlığı, model/uzak servis
çağrılmıyor dürüstlüğü korunarak) güncellendi. Temiz çıkanlar: PREFERENCES passage
bölümü, MARKDOWN #92 sözleşmesi, SKILL.md, memory-types.md, release banner'ı (3.4.0
M2 ile geldi). Klon single-branch olduğu için `origin/main` hiç yoktu; refspec'e
`main` eklendi ve worktree'deki lokal main `f9a8b5f`'e ff'ledi (dal 28 commit ileride).
Tarihsel dosyalara (V2, deadend, oturum notları) ilkesel olarak dokunulmadı.

## Günlük oturum logu — model'siz B1 (2026-09-26): 746/746 yeşil (+8)

Hook olguları yazar (aç/kapat bloğu, saat-harness-istem sayısı, receipt pencereleri,
yarıda-kalan işareti), özeti oturumdaki ajan beş V2 başlığıyla doldurur; `daily_log`
opt-in, varsayılan kapalı; transcript/k Model çağrısı yok. TDD: 8/8 hedefli (gerçek
hook subprocess dâhil) → tam paket 746/746. Tasarım, reddedilen A/B1 sentezi gerekçesi
ve PR savunması: `docs/specs/2026-09-26-daily-log-design.md`.

## Altın kurallar ve "MindFork Lite" dış plan değerlendirmesi (2026-09-26)

Dışarıdan gelen "MindFork Lite" birleşik yol haritası (Workbench + `mindfork.py`
kapısı + satır araması + YAML filtre + `weight` ısı haritası + damıtma akışı)
denendi ve **toptan reddedildi**: maddelerin çoğu sistemde zaten var ve daha
gelişmiş/testli sürümde (CLI tek-yazıcı kapısı, FTS5 BM25 + passage strict,
frontmatter filtreleri, tek odak devir kartı + `daily/log` oturum blokları,
Altın Kural 3'ün stdlib-only ilkesi). Reddedilen öğeler: sıfırdan paralel sistem
(746 testlik motoru ikiye böler, "AI rastgele yazıyor" varsayımı V3 mimarisine
aykırı), substring satır araması (mevcut BM25/passage'ın gerisinde), arama
sırasında `weight` yazma (read-only sözleşmesini kırar), "tek kapı/multi-harness
gereksiz" (ürünün kendisi: 6 istemci), `date.now` benzeri modeller dışı.

**Alınan üç kazanım:**
1. **Isı haritası → AutoDream-lite'a, pasif alıntıyla.** Sorgu günlüğü tablosu
   **yoktur** (motor yalnız `receipts(payload.refs)` tutar); bu yüzden birincil ısı
   sinyali pasif alıntı frekansıdır (receipt → `daily/v3` projeksiyonu → not
   başına alıntı). Yazma yalnız konsolidasyon penceresinde olur; retrieval
   sıralamasına ağırlık sokulmaz. Tasarım: `docs/specs/2026-09-26-autodream-lite-roadmap.md`
2. **Altın Kural (yeni, süreç kuralı):** Yeni kalıcı özellik, mevcut mekanizmayla
   en az bir hafta gerçek kullanım ölçümü yapılmadan eklenmez. İhtiyaç
   kanıtlanmazsa kod yazılmaz (Lite planının "bir hafta dene + kontrol noktası"
   disiplininin genelleştirilmiş hâli; kendi hedefi de dahil: ölçüm geçmiyorsa
   `--types/--strict` bayrakları da yazılmaz). **Kapsam netleştirmesi:** kural
   *sıcak yol* (retrieval/hook) değişikliklerini bağlar; kullanıcı çağrılı pencere
   komutları (`dream`) ve skill kuralları ölçümün kendisini üretir, kapı dışındadır.
3. **Damıtma öncesi kopya → zorunlu ön-image.** Lite "workbench kopyası iki hafta
   saklansın" önerisi, bizim mimaride maskelenmiş biçimde daha kritik bir riski
   kapatır: Prune/Merge geri döndürülemez. AutoDream penceresi, etkilenecek her
   dosyanın ön-image'ını `archive/auto-dream/<tarih>/files/` altına manifest
   sha256 ile alır, `dream --restore` ile birebir geri alınır (test sha256 kümesi
   ile assert eder).

## Dış doğrulama ve "tam AutoDream" kararı (2026-09-26)

Dış metin (*Beyond the Session: Memory Engineering for Agent Teams*, 2026-04-21)
denetlendi. **Kaynak uyarısı:** metinde anlatılan AutoDream/KAIROS ayrıntıları
Anthropic'in *yayımlanmamış* iç yapısına ilişkin üçüncü-taraf sızıntı
raporlarından gelir; birincil doğrulama yok — bu yüzden kayıt ve PR metinlerinde
"doğrulanmış ürün davranışı" değil **"ilham alınan dış desen"** olarak geçer.

Konverjans (bizde zaten var, PR'da kullanılabilir kanıt): üç bellek boyutu —
`VALID_MEMORY_TYPES = ("episodic","semantic","procedural")` birebir; pre-task
hydration / post-task konsolidasyon ayrımı; aday belleğin terfi incelemesi
metaforu (bizim staging→sync + karantina hattı); hybrid BM25+vektör+RRF
(Cloudflare'ın 5-kanallı RRF vardığı yazıda bağımsız olarak aynı sonuca
varıyor); boyut disiplini; tarih mutlaklaştırma; 3 kapı + kilit. Alınmayanlar:
Redis/NATS, Temporal, bulut dosya deposu, vektör DB bağımlılığı, organizasyon
ikinci bellek katmanı — organizasyon ölçeğinin altyapısı, tek kullanıcılı yerel
vault'ta Altın Kural 3'ün ihlali.

"Tam AutoDream" üçe ayrıldı: (1) **4 faz + 3 kapı + ön-image** → modelsiz
benimseniyor (`docs/specs/2026-09-26-autodream-lite-roadmap.md` §0-§5);
(2) **model küratörü** → `--llm` fazı **reddedildi**: kullanıcının çalıştırabileceği
yerel model yok, uzak API ise "uzak servis çağrısı yok" ilkesini ihlal eder —
muhakeme zaten oturumdaki ajanın işi; (3) **KAIROS daemon** → yapılmaz, ama kapılı
ve idempotent `dream` komutu kullanıcının kendi cron/systemd timer'ıyla
çağrılabilir (paket daemon'laşmaz).

Uygulama sırası: A+F (kapılar + metadata + bu bölüm) → C (doctor `oversize`) →
B+D (SKILL kuralları) → faz-1 `--dry-run` ölçümü → ≥1 hafta ölçüm → faz 2-5 kararı.

## Konsolidasyon penceresi faz 1 + günlük log Faz-2 (2026-09-26, `feat/memory-consolidation`)

Yeni dal açıldı (dal geçmişi silinmedi; konu-bazlı commit'ler zaten ayrıydı). Teslim:
`beyin.py dream` (üç kapı + boyut envanteri + pasif alıntı ısısı + Prune/Merge/Refresh
adayları, **hiçbir şey yazmaz**), motorun dört salt-okunur erişimi, `doctor.oversize`,
günlük log Faz-2 (kapanış kaydı gelmeyen oturum gerçek kayıtla kapanır), iki SKILL kuralı
(mutlak tarih; iş-akışı tipi öğrenim `procedural`).

Kanıt: TDD 19 dream + 12 günlük log + 3 doctor (hedefli 91/91), tam paket iş sonunda.
Canlı test vault'unda üç kapı, kilit yarışı ve `wrote: false` doğrulandı. Yol üstünde üç
gerçek hata bulundu ve düzeltildi: kilit probu kendi dosyasını oluşturuyordu; merge kuralı
senkronlanan kayıtlarda **olmayan** `title` alanını okuyordu (canlı testte yakalandı, kural
`title → ilk başlık → dosya adı` zincirine çevrildi); companion bütçeleri çıplak addı
geliyordu. Bir spec çelişkisi de düzeltildi: filigranı tüketen rapor kendi ölçüm haftasını
kapatırdı, artık kapılar mutasyonlu pencereyi uygular, rapor yalnızca bildirir.
Tasarım: `docs/specs/2026-09-26-autodream-lite-roadmap.md` §11, `...-daily-log-design.md`.

## Kurulum yolunda canlı E2E (2026-09-26): bir P0 bulundu

Bu dalın paketi gerçek bir vault'a kurulup ajanın kullandığı yolun tamamı
geçirildi (`/tmp/beyin-full-e2e`): kurulum → oturum döngüsü → receipt/öğrenim →
not/görev kapıları → tip süzgeci → doctor/dream → çökme telafisi → kural bütünlüğü.

**Bulunan hata (P0):** `_portalock.py` alt çizgiyle başladığı için kurulumun
`beyin_v3*.py` glob'una girmiyordu; vault'a hiç kopyalanmıyordu. Birim testleri
bunu göremez (kaynak ağacında her modül kardeştir), ama gerçek vault'ta
`beyin_v3_sessionlog` ve `beyin_v3_dream` bu modülü import edemiyor → **günlük log
hiç açılmıyor**, hook'un `try/except` sayesinde sessizce düşüyor. Dört yer birden
düzeltildi: kurulum, paket bütünlük denetimi, release listesi ve güncelleyici
allowlist'i; dördü de `install_v3.RUNTIME_MODULES()` tek kaynağına bağlandı.
Regresyon testi: kurulumdan sonra **yalnız vault'un kendi dizini** sys.path'te
olacak biçimde her kurulu modül import edilir (v3_product_test).

Diğer doğrulamalar: not üzerine yazma reddi, strict görevde kanıtsız `done`
reddi, revision çakışması, geçersiz tip reddi, alıntı dışı/traversal/boş refs
reddi, sır süzgeci (`[REDACTED]`, ham anahtar DB'de yok), receipt idempotency'si ve
farklı gövdeyle çakışması, öğrenim hatırlatması (bir kez, `decision: block`),
çökme telafisi (`(kapanış kaydı yok)` + son etkinlik), tipsiz eski notun
filtresiz kalması. **Kural bütünlüğü:** akış boyunca 21 meşru yeni dosya, **0
değişen, 0 silinen**; `Kurallar.md`, `Core.md`, `Last-Session.md`, `Threads.md`,
`Journal.md` bayt bayt aynı — sistem kuralı kendi kendine yazmıyor.

İki bilinen boşluk teyit edildi: `context` CLI'da `--types` yok (motor
destekliyor; ertelenen roadmap işi) ve normal CLI çağrıları vault'a `__pycache__`
yazıyor (temizlik, işlevsel değil).

## Upstream birleştirme 3 (2026-09-26, `a680338`): bir çakışma, ikisi de

`upstream/main` `f9a8b5f` → `db1f23d` (14 commit, 16 dosya): bilesen/skill haric
tutma (#108), kaynakli yakin donem ozeti / recap (#111), state koku cozumleme-
sabitleme (#113/#114). Kuru deneme (`merge-tree`) **tek** icerik cakismasi
gosterdi; 6 cift-dokunuslu dosya kendiliginden birlesti.

Cakisma `scripts/beyin_v3.py` `preferences` alt komutundaydi: iki taraf da ayni
bloga bagimsiz ozellik eklemisti (biz `--daily-log`, upstream
`--exclude/--include-component`). **Ikisi de korundu** — cakismanin disindaki
`result['excluded_components'] = result_excluded` satiri upstream blogu zorunlu
kiliyordu; "upstream kazanir" burada yanlis olurdu. Kanit: ayni komutta exclusion
yazildi/geri alindi, `daily_log` bagimsiz kapandi/acildi, exclusion
`.beyin-exclusions.json`'a yazildi (tercih semasinda degil).

**Paketleme denetimi (asil kazanim):** `RUNTIME_MODULES()` glob
(`beyin_v3*.py`) kullandigi icin upstream'in yeni `beyin_v3_exclusions.py`
modulu manifest'e **otomatik** girdi (29 modul), `beyin_v3_update.py` allowlist
regex'i de onu kapsiyor. 5f68006'daki tek kaynakli liste bu dalgayi bedava
karsiladi; o olmasaydi yeni modul yalniz gercek vault'ta import hatasi verirdi.
`projections.py`'de bizim `PROJECTION_GUARD` ile upstream'in
`_hidden_ref_sources` bagimsiz bolgelerde bir arada duruyor.

**837/837 yesil** (skipped=1): 806 bizim + 31 upstream'in yeni testleri, ilk
kosuda sifir kirik — onceki spec'lerde yazili "buyuyen paket ilk kosuda bilinmeyen
kirik uretebilir" riski gerceklesmedi.

## AutoDream faz 2: snapshot + Refresh + geri al (2026-09-26)

Faz-1'in "≥1 hafta gerçek kullanım ölçümü" şartını 30 sanal günlük ay sürücüsü
doldurdu (kapılar gerçekten reddetti, üç aday türü de rapora düştü, elle uygulama
yalnız beklenen dosyayı değiştirdi). Kalan eksik mutasyonun geri alınabilirliğiydi.

`dream --apply` artık kapıları **uygular**, kilidi alır, dokunduğu her dosyanın
ön-image'ını `archive/auto-dream/<tarih>/files/` altına kopyalar, `manifest.json`
(sha256) yazar, Refresh'i uygular, `report.md` üretir, dizini yeniden kurar ve
**yalnız gerçekten bir şey yazdıysa** filigranı ilerletir. `dream --restore
<tarih>` hash'i doğrulayıp geri yükler; tutmuyorsa reddeder, sessiz bozma yoktur.
`--force` zaman/receipt kapılarını atlar, kilidi asla.

**Refresh kapsamı bilinçli daraltıldı** (§5.1): kod yalnız makineye ait alanları
yazar (başlık/ayraç, çözülebilen frontmatter tarihi), gövdedeki bağıl tarihleri
`prose_dates` olarak **raporlar** ve metne dokunmaz. İki gerekçe: "dün"ün hangi
güne çözüleceği belirsizdi, ve insan cümlesini kodun yazması ajanın yetkisini
bayatlatırdı. Yan fayda: SKILL'deki "mutlak tarih yaz" kuralı artık ölçülebilir
bir ihlal listesine dönüştü.

Yol üstünde **dört gerçek hata** bulundu ve düzeltildi: kilit ters bildiriliyordu
(her `--apply` kendi kilidini "başkası almış" sanıyordu), frontmatter değişikliği
raporlanıyordu ama yazılmıyordu ve kapatıcı `---` satır sonunu yutuyordu,
`prose_dates` katlanmış metni dösteriyordu, `updated` tazelemesi gövdesi
değişmeyen notları aramada öne atacaktı. Hepsi kendi kırmızı testleriyle yakalandı.
Ayrıca üç test fixture'ı aday tavanının altında kaldığı için biri "idempotans"
testi **trivially** geçiyordu; bunu yakalayan `assert_refresh_candidate()`
yardımcısı eklendi.

**Geri al kanıtı iki yerde ölçüldü:** 21 yeni senaryo ve gerçek kurulumda (ay
sürücüsü q15: apply → restore → vault bayt bayt aynı). Tam paket **859/859** yeşil.

Yarıda kalan: faz 3 Merge, BULGU 8'i ön koşul olarak bekliyor (başlık tabanlı aday
eşleşmesi + kalıcı "çözüldü" durumu yok).

## AutoDream faz 3: BULGU 8 kapandı + ajan planı (2026-09-26)

Faz-3, bir aylık insan kullanımı E2E'sinin bulduğu **BULGU 8'i** kapattı: bir aday
çözülmüş sayılmıyordu, çünkü eşleşme yalnız başlığa bakıyordu ve "çözüldü" durumu
hiçbir yerde tutulmuyordu. Birleştirip aynı başlığı taşıyan bir işaretçi bırakmak
adayı temizlemiyordu.

- **Aday eşleşmesi** başlık alt-kümesi **veya** gövde örtüşmesi (gövde token'ları
  retrieval ile aynı gövdeleyiciden; en az 3 ortak token ve küçük kümenin %50'si).
  Aday `matched: title|body` ile gerekçesini bildirir.
- **İşaretçi tespiri:** kısa not hedefin vault-göreli yolunu anıyorsa aday düşer.
  Yanlış susturmayı önleyen koşul: not hedefin karakterinin ≤%40'ı olmalı.
- **Kalıcı dismiss:** `archive/auto-dream/dismissed.json` (vault içi — içerik kararı,
  reinstall'da kaybolmamalı) + `dream --dismiss`. Bozuk dosya pencereyi **durdurmaz**,
  uyarıyla geçilir.
- **`--apply` gövdeyi yazmaz:** çiftleri snapshot'lar ve `merge-plan.md` yazar
  (hangi not hayatta kalacak, ortak sözcükler, ajana talimat). Birleşen metin
  ajanın işi (§4).

**Yol üstünde dört gerçek hata:** (1) `archive/` indeksleniyordu, yani her ön-image
bir not oluyor ve kaynak not **kendi kopyasıyla** eşleşiyordu — yalnız CLI yolunda
görünürdü, `EXCLUDED_DIRS`'a `'archive'` eklendi; (2) diskte **olmayan** notun
kaydı kaldığında hayalet aday üretiliyordu; (3) gövde kuralı bir **notu bir görevle**
eşleştiriyordu (aynı `kind` şartı); (4) aynı kaynağın iki kaydı kendini aday
gösterebiliyordu.

Test tarafında da üç sessiz hata: `pairs()` sıra duyarsızdı ve "işaretçi önerilmiyor"
testini **trivially** yeşile çeviriyordu; birleştirilmiş not fixture'ı gerçekçi
olmayan kadar kısaydı (kural yanlış değildi, çerçeve yanlıştı); faz-1'in iki merge
testi kayıtları **dosyasız** tohumluyordu.

**Ay sürücüsü q16** gerçek kurulumda kanıt: iki ödeme notu aday çıkıyor, ajan
birleştirip işaretçi bırakıyor, aday düşüyor. Tam paket **875/875** yeşil.

### Yeni bulgu (faz-3'ün kararı değil, ölçüldü ve kayda geçti)

**Bir işaretçi not, birleştirilmiş notu aramada geçersiz kılabiliyor.** Konsolidasyon
"yinelenen notu sil" yerine "işaretçi bırak" biçiminde denendi (kaynak bağlantıları
çözülü kalır diye daha iyi bir uygulama) ve `odeme icin ne karar vermistik` sorusunda
arama **85 karakterlik işaretçiyi** 378 karakterlik gerçek notun önüne geçirdi:
kısa notun az kelimesi yüksek ağırlık alıyor. Bu retrieval sözleşmesine yeni bir madde
demek (işaretçi işareti + kapı), faz-3'ün kapsamı değil. Sürücü bu yüzden orijinal
davranışında tutuldu. **Sıradaki iş kalemi.**

## Kalan işler

0. **İşaretçi notun retrieval'daki yeri** (2026-09-26, faz-3 ölçümü): birleştirme
   sonrası bırakılan işaretçi not, kısa olduğu için birleşik notu aramada geçersiz
   kılabiliyor. Karar gereken: işaretçi için frontmatter işareti (örn. hedef yol) ve
   retrieval kapısı mı, yoksa merge pratiği "sil" mi kalmalı. Ölçüm ve iki seçenek
   `docs/specs/2026-09-26-autodream-phase3-merge-plan.md` sonuç bölümünde.

1. Gerçek embedding sağlayıcısı (semantic_searcher şu an kanca; Ollama/API opsiyonel)
2. AutoDream-lite faz 4-5 (onaylı Prune → re-index). Faz 1 (ölçüm), faz 2
   (snapshot/Refresh/`--restore`) ve faz 3 (merge adayı + dismiss + ajan planı)
   **TAMAMLANDI** (2026-09-26); BULGU 8 gerçek kurulumda (q16) doğrulandı. Kural ve
   kapsam `docs/specs/2026-09-26-autodream-lite-roadmap.md` §10 + §5.1 + §5.3
3. Strict passage yoluna tip kapısı devri (#83 sonrası bilinen port boşluğu) — **TAMAMLANDI** (2026-09-25): kapılar arama anında `allowed` id kümesiyle uygulanıyor, index/df/FLOOR kalibrasyonu korunuyor; tasarım + sonuç `docs/specs/2026-09-25-passage-type-gate-design.md`
4. PR ile main'e birleştirme (fork main upstream ile senkron: `db1f23d`; dal `feat/memory-consolidation` = `a680338`)
5. CLI `context --types/--strict` bayrakları (canlı E2E bulgusu #1; kararlı tasarım + test planı `docs/specs/2026-09-25-cli-context-types-strict-roadmap.md`)
6. Günlük log Faz-2: PreCompact kurtarma çizgisi (spec'te ertelenen kemer)
8. V3 mimari haritası ve değişmezler: `2026-09-27-mimari.md` (katmanlar, veri
   akışı, değişmezlerin zorlama yerleri, bu dalda ölçülmüş tuzaklar)
7. ~~OpenCode kapanış olayı yok → yetim bloğu kapatma~~ **TAMAMLANDI** (2026-09-26):
   blok "kapanış kaydı yok" etiketiyle kapanıyor, son etkinlik ve receipt penceresi
   yazılıyor; canlı opencode akışıyla doğrulandı
