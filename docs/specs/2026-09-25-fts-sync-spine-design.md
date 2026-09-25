# FTS ↔ Sync Yazma Omurgası (derived-write spine) — Tasarım

Tarih: 2026-09-25 · Dal: feat/explicit-memory-typing · Durum: ONAYLANDI (Fix-1→4)
Kaynak: ikinci harici mimari inceleme; P0 iddiası kanıtla doğrulandı.

## Problem (kanıtlı)

FTS5 türetilmiş indeksi yalnız `MemoryStore.ingest` (:389) ve `update_task` (:411) tarafından
güncelleniyor; üretim yazma yolu `SyncEngine.sync()` ham SQL yazıyor (`beyin_v3_sync.py:521`
DELETE, `:538` INSERT OR REPLACE) ve `records_fts`'e hiç dokunmuyor. Rebuild tetiği
`fts_count == 0`. Sonuç, salt-sync vault'ta:

1. İlk açılış rebuild'i bir ANLIK GÖRÜNTÜ alır; sonraki her senkron FTS'i eskityor.
2. Yeni notlar FTS'te hiç görünmüyor → BM25 onları hiç göremiyor.
3. Silinen notlar yetim FTS satırı bırakıyor; yetimler `fts_count > 0` tutarak rebuild'i
   kalıcı kilitliyor.
4. BM25 sırası, overlap admission'ın taze payload'ları üzerinde donmuş bir görüntüyle
   hâkimiyet kuruyor → yanıltıcı sıralama (yamadan fena).

Kök neden (dürüst özeleştiri): Aşama-2 testleri yalnız `ingest` üzerinden yazıldı; sync
yazma yolu test edilmedi. "Atomik FTS senkronu" iddiası store kapısı için doğru, sync
kapısı için hiç kurulmamıştı.

## Tasarım

### Fix-1 — tek derived-write omurgası
`MemoryStore` statikleri (facts_str katlaması dahil TEK yerde):
- `fts_write(db, record)`: `DELETE FROM records_fts WHERE id=?` + `INSERT ...`.
  DELETE önce: çağrı anında satırın var/yok olması sorgulanmaz;幂etkisi idempotent.
- `fts_delete(db, id)`: tek DELETE.
Kullanıcılar: `ingest` (mevcut literal → `fts_write`), `update_task` (mevcut delete+insert
→ `fts_write`), `SyncEngine.sync()` delete döngüsü → `fts_delete`, insert/update kolu →
`fts_write` — hepsi ZATEN AKTAAN OLAN aynı `BEGIN IMMEDIATE` transaction içinde.
Sync, `beyin_v3`'ten `MemoryStore`'u zaten import ediyor (:19); yeni bağımlılık yok.

### Fix-2 — FTS parmak izi + kendini onarım + doctor
- `_FTS_PARAMS = [FTS_SCHEMA_VERSION, tokenizer-imzası]`; rebuild başarıyla tamamlanınca
  `metadata('fts_params')` yazılır.
- Açılış tetiği: `stored != _FTS_PARAMS` VEYA `fts_count == 0` (kayıt varsa) → rebuild.
  Bu, drift'lenmiş mevcut vault'ları sürüm yükseltmesinde tek seferde onarır (imza yok →
  rebuild → senkron yazma yolu bundan böyle drift üretmez).
- Doctor (kök CLI, bilgi amaçlı; status sözleşmesi DEĞİŞMEZ):
  `result['fts_consistency'] = {'records': n, 'indexed': m, 'orphans': k}`
  — tek SELECT + LEFT JOIN, salt okunur.
- Not: `fts_malformed_skipped` anlamı "son rebuild'te atlanan" (üzerine yazılır); belgelendi.

### Fix-3 — tip sabiti tek kaynak
`beyin_v3_sync.py` içindeki iki `valid_types = ('episodic', 'semantic', 'procedural')`
literalı → import edilen `VALID_MEMORY_TYPES`.

### Fix-4 — context_for fail-fast
`store.context_for`, passage dispatch'inden önce `resolve_type_filter(query, types)` çağırır
(değer ValueError olarak patlar; fallback-üçlü-yeniden-doğrulama artık davranış değil tembellik
değil — testle pin: `store.context_for(..., types='bogus')` ValueError).

## Retler (incelemeciye reddiye, kayıt)
SQL visibility/project indeksleri ve MATCH içi `type:` ön-filtresi → hook zaten O(vault)
dosya yürütüyor; ölçüm (evaluate harness) öncesi red. Trust alan-çantası, audience kopyaları,
events retention, cadence/çok-cihaz, dup-id karantina kimlik modeli, Markdown↔SQLite çift
gerçeklik penceresi → upstream sahipliği; fork'ta çatal bakımı üretir, PR/contribution
listesine. JEV aday havuzunun tipten habersizliği → tasarım gereği (havuz kapısız, teslim
kapılı); incelemecinin "JEV ayrı gate kopyası" okuması yanlış (jev._eligible → store._retrieve
delegasyonu).

## Testler (önce kırmızı)
`tests/custom/v3_fts_sync_spine_test.py`:
1. sync ile not ekle → FTS MATCH yeni tokenı görür.
2. dosyayı değiştir + sync → FTS yeni metni taşır (eski token MATCH boş).
3. dosyayı sil + sync → records ve records_fts'ten kalkar; `fts_consistency.orphans == 0`.
4. drift'li eski DB (FTS donmuş, imzasız) → yeniden açılışta rebuild → taze metin indeksli,
   `fts_params` yazılı.
5. store-context fail-fast ValueError pini.
Mevcut doctor sözleşme testleri (fts_consistency anahtarının varlığına bakmaz) etkilenmez.

## Uygulama sonucu

- Fix-1: `MemoryStore.fts_write/fts_delete` statikleri tek yazıcı; `ingest`, `update_task`,
  rebuild ve `SyncEngine.sync()` (aynı `BEGIN IMMEDIATE`) hepsi bu omurgayı kullanıyor.
- Fix-2: `FTS_PARAMS` imzası + açılışta imza-farksa-rebuild → drift'li eski DB'ler tek
  seferde kendini onarıyor; doctor `fts_consistency {records, indexed, orphans}` ekledi.
- Fix-3: sync `valid_types` literalleri → `VALID_MEMORY_TYPES` importu.
- Fix-4: `context_for` dispatch öncesi `resolve_type_filter` fail-fast (pin testiyle).
- TDD: 3 kırmızı (add/edit/delete, self-heal, doctor) + 1 yeşil pin → hedefli 45/45 →
  tam paket **738/738**. Read-only store açılışı rebuild bloğuna hiç girmiyor (dosya
  akışı yazılabilir açıkta onarılır; hook çökmez).
- Reddiye listesi bu dosyada; inceleme tartışmasının tam kaydı seans notlarında.
