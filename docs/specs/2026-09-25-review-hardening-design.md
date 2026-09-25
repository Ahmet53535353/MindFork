# İnceleme Sertleştirme Seti (external review hardening) — Tasarım

Tarih: 2026-09-25 · Dal: feat/explicit-memory-typing · Durum: ONAYLANDI (madde 6 dahil)
Kaynak: harici model incelemesi; her iddia koda karşı doğrulandı (bkz. oturum kaydı).
Ret edilen öneriler (SQL ön-filtre, tek analizör) aynı dosyada gerekçeli.

## Kapsam (onaylı 6 madde)

### 1. `supersedes` savunması (kabul, ciddi-seviye düzeltmeli)
`_retrieve:654` ve `beyin_v3_passage.pool:362` → `record.get("supersedes", [])`.
Gerekçe: her yazım `_validate`'ten geçer (varsayılan garanti), dolayısıyla yalnız manuel DB
müdahalesiyle ulaşılabilir; ancak FTS bozuk-payload sayacımızın kanıtladığı gibi gerçek
vault'larda bozulma görülüyor. `visibility`/`json.loads` gibi diğer doğrudan erişimler
bilinçli kapsam dışı (fail-closed sözleşmesi; tek alanlık savunma tutarlılık illüzyonu
yaratmaz, sadece en olası eksik-anahtar vakasını ucuzlatır).
Test: payload'dan `supersedes` anahtarını DB düzeyinde sil → hem `retrieve` hem passage
`context_for` çalışmaya devam eder.

### 2. `types=[]` artık ValueError
`resolve_type_filter`: boş liste/tuple/set → `ValueError("memory type filter must not be
empty")`. Sessiz boş bağlam, gürültülü hatadan kötüdür (hook yolu).

### 3. Strict-yol FTS atlaması
FTS bloğu `if query and query.strip() and not (strict and not snapshot)` koşuluna alınır
(snapshot korumalı — snapshot dalı haritayı KULLANIYOR). Davranış değişmez (harita atık),
gereksiz sorgu gider. Test: `records_fts` tablosunu düşür → strict retrieve hatasız + sayaç
yok; non-strict → `fts_query_errors` sayacı artar (madde 6 ile birleşik gözlem).

### 4. Dokümantasyon düzeltmeleri
- `memory-types.md:44`: "metadata.type zorunludur" → gevşetilmiş sözleşmeyle uyumlu metin
  (M1'de kaçan düzeltme — bizim hatamız).
- Plan dosyasındaki `file:///home/hayalet/...` → göreceli yol.

### 5. Sıralama semantiği: belge + sıra-testleri
Gercek sıralama (non-strict): overlap = admission eşiği; BM25 rank = hâkim sıralama;
BM25'te görünmeyenler skor/güncellik sırasıyla kuyrukta; semantik kanca RRF ile füzyon.
Belge: RUNTIME.md İngilizce tek cümle + record karar satırı.
Testler: (a) BM25'in güncellik/overlap'i ezip sıralamayı değiştirdiği, (b) FTS satırı
silinmiş kaydın BM25 vuruşlarının SONRINA düştüğü, (c) füzyon entegrasyonunda `fused[0]`
assertu (mevcut assertIn zayıftı), (d) `semantic_searcher` exception → lexical sıra bozulmaz.

### 6. Sessiz-düşüş sayaçları (gözlemlenebilirlik)
`_count_retrieval_error(key)` yardımcı: read_only'yse yazmaz; hata yolunda metadata
`fts_query_errors` / `semantic_search_errors` artırır (kendi içinde sessiz). Kök CLI doctor
çıktısına bilgi amaçlı eklenir (status sözleşmesi değişmez; `fts_malformed_skipped` kalıbı).

## Retler (kayda değer)
- `id IN (...)` / `type IN (...)` SQL ön-filtresi: kapı politikası tek kaynakta (Python)
  kalmalı; yumuşak kapı + supersede + tazelik SQL'e kopyalanırsa iki gerçek doğar. Corpus-wide
  BM25 idf standarttır. Ölçmeden optimizasyon yok.
- Tek analizör birleştirmesi: iki analizör bilinçli tamamlayıcı (stem ↔ ham sembol); cache
  rebuild güvencesi `_PARAMS`/stem-imzasında zaten var.

## Test dosyaları
`tests/custom/v3_fts5_test.py` (FTS hâkimiyeti, kuyruk, strict-atlama, sayaçlar),
`tests/custom/v3_rrf_hybrid_test.py` (fused[0], semantic düşüş+sayaç),
`tests/custom/v3_memory_types_test.py` (types=[] ValueError),
`tests/custom/v3_passage_types_test.py` (supersedes-savunması passage'da).

## Uygulama sonucu

- 1-3, 6: kod değişiklikleri uygulandı (`types=[]` → ValueError; `_retrieve`/`pool` `.get`;
  strict FTS atlama snapshot-korumalı; `_count_retrieval_error` + iki yutma noktası; kök CLI
  `retrieval_error_counters`). TDD: 5 kırmızı → 31/31 hedefli yeşil.
- 4: memory-types.md kural-2 gevşetilmiş sözleşmeye çekildi (M1 kalıntısı); plan dosyasındaki
  `file://` yolu göreceli oldu.
- 5: sıralama semantiği PREFERENCES.md'ye iki madde olarak yazıldı (karar + sözler);
  BM25-hâkimiyet/kuyruk + fused[0] + phantom-retmi + semantic-düşüş testlerle kilitli
  (BM25 pin'i uygulama ÖNCESİNDE de yeşildi — davranış değişikliği değil, pekiştirme).
- Tam paket sonucu ve commit: record dosyasında.
