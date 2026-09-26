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
   `--types/--strict` bayrakları da yazılmaz).
3. **Damıtma öncesi kopya → zorunlu ön-image.** Lite "workbench kopyası iki hafta
   saklansın" önerisi, bizim mimaride maskelenmiş biçimde daha kritik bir riski
   kapatır: Prune/Merge geri döndürülemez. AutoDream penceresi, etkilenecek her
   dosyanın ön-image'ını `archive/auto-dream/<tarih>/files/` altına manifest
   sha256 ile alır, `dream --restore` ile birebir geri alınır (test sha256 kümesi
   ile assert eder).

## Kalan işler

1. Gerçek embedding sağlayıcısı (semantic_searcher şu an kanca; Ollama/API opsiyonel)
2. AutoDream-lite konsolidasyon motoru (ölçüm → snapshot/Refresh → Merge → onaylı Prune → re-index; ısı ve restore kuralları: `docs/specs/2026-09-26-autodream-lite-roadmap.md`)
3. Strict passage yoluna tip kapısı devri (#83 sonrası bilinen port boşluğu) — **TAMAMLANDI** (2026-09-25): kapılar arama anında `allowed` id kümesiyle uygulanıyor, index/df/FLOOR kalibrasyonu korunuyor; tasarım + sonuç `docs/specs/2026-09-25-passage-type-gate-design.md`
4. PR ile main'e birleştirme (fork main zaten upstream ile senkron: f9a8b5f)
5. CLI `context --types/--strict` bayrakları (canlı E2E bulgusu #1; kararlı tasarım + test planı `docs/specs/2026-09-25-cli-context-types-strict-roadmap.md`)
6. Günlük log Faz-2: PreCompact kurtarma çizgisi (spec'te ertelenen kemer)
7. OpenCode kapanış olayı yok (`session.deleted` yalnız silmede) → yetim bloğu
   "yarıda kaldı" yerine "kapanış alınamadı · son etkinlik HH:MM" diye kapatma
   (~30 dk; günlük-log spec'i Faz-2)
