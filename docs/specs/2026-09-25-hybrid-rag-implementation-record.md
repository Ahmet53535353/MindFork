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

## Test durumu

- Aşama sonu kilometre taşları: 466/466 → tip sezgisi + discovery düzeltmesiyle 493/493.
- **Upstream merge sonrası: 673/673 yeşil** (`python3 -m unittest discover tests -p "*test.py"`; upstream'in ~200 yeni testi dahil, skipped=1 platform testi).
- **Passage tip kapısı sonrası: 681/681 yeşil** (+7: `v3_passage_types_test`).
- Custom testler `tests/custom/` içinde (`__init__.py` sayesinde kök discover artık dahil ediyor):
  - `v3_memory_types_test.py` — tip doğrulama ve filtreleme
  - `v3_fts5_test.py` — FTS5 şema, senkron, rebuild, tam sembol araması, bozuk payload toleransı
  - `v3_rrf_hybrid_test.py` — RRF matematiği ve semantik kanca
  - `v3_companion_ends_fill_test.py` — iki uçlu kırpma bütçe dolumu
  - `v3_type_inference_test.py` — ipucu birim testleri, yumuşak kapı, override, entegrasyon
  - `v3_passage_types_test.py` — passage yolunda tip kapıları: yumuşak/açık filtre, override, cache-değişmezliği, ValueError sırası
 
## Kalan işler

1. Gerçek embedding sağlayıcısı (semantic_searcher şu an kanca; Ollama/API opsiyonel)
2. AutoDream-lite konsolidasyon motoru (Prune/Merge/Refresh/Re-index + boyut disiplini)
3. Strict passage yoluna tip kapısı devri (#83 sonrası bilinen port boşluğu) — **TAMAMLANDI** (2026-09-25): kapılar arama anında `allowed` id kümesiyle uygulanıyor, index/df/FLOOR kalibrasyonu korunuyor; tasarım + sonuç `docs/specs/2026-09-25-passage-type-gate-design.md`
4. PR ile main'e birleştirme (fork main zaten upstream ile senkron: f88fa59)
