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

## Teknik kararlar

- Tip filtresi: types=None (tümü) / str / list; geçersiz tipte ValueError; geriye dönük uyumlu.
- FTS5: unicode61 remove_diacritics 2; ingest/update BEGIN IMMEDIATE içinde records_fts ile atomik.
- FTS sorgusu durak kelimeleri içermez (gürültü aday patlamasını önler).
- Dense rank: eşit BM25 skorları aynı sırayı alır → stabil sıra (güncellik, sonra id) bozulmaz.
- RRF: k=60; vektör motoru yokken saf BM25 sırası korunur; semantic_searcher callable iken füzyon.
- Companion ends(): satır sınırı kırpmanın bıraktığı boşluk ortadan kapanışa doğru geri doldurulur; suyla-doldurulmuş bütçe çöpe gitmez.

## Test durumu

- 466/466 yeşil (`python3 -m unittest discover tests -p "*test.py"`)
- Custom testler `tests/custom/` içinde:
  - `v3_memory_types_test.py` — tip doğrulama ve filtreleme
  - `v3_fts5_test.py` — FTS5 şema, senkron, rebuild, tam sembol araması
  - `v3_rrf_hybrid_test.py` — RRF matematiği ve semantik kanca
  - `v3_companion_ends_fill_test.py` — iki uçlu kırpma bütçe dolumu

## Kalan işler

1. Gerçek embedding sağlayıcısı (semantic_searcher şu an kanca; Ollama/API opsiyonel)
2. Sorgudan otomatik type sezgisi (episodic/semantic/procedural otomatik atama)
3. AutoDream-lite konsolidasyon motoru (Prune/Merge/Refresh/Re-index + boyut disiplini)
4. PR ile main'e birleştirme
