# Mimari Tasarım: Type-Based Retrieval ve Hybrid RAG (BM25 + RRF)

**Tarih:** 2026-09-25  
**Durum:** Taslak (Onaylandı)  
**Hedef:** MindFork (Beyin v3)  
**Referans:** Jordan Carson — *"Beyond the Session: Memory Engineering for Agent Teams"*  

---

## 1. Genel Bakış ve Amaç

Bu tasarım, bellek mühendisliğinin iki kritik bileşenini MindFork (`beyin_v3`) çekirdeğine kazandırır:
1. **Tip Bazlı Getirme (Type-Based Retrieval / Pre-filtering):** Notların türüne (`semantic`, `procedural`, `episodic`) göre filtrelenerek ajanın bağlamına yalnızca ihtiyaç duyduğu türdeki bilginin yüklenmesini (Context Hydration) sağlamak ve gürültüyü önlemek.
2. **Hybrid RAG Arama Motoru (BM25 + RRF + Vektör Arayüzü):** Kod tabanlarında kod sembollerini, dosya adlarını ve kesin hata mesajlarını yakalamak için **SQLite FTS5 (BM25)** leksikal araması ile anlamsal aramayı **Reciprocal Rank Fusion (RRF)** formülüyle birleştirmek.

Bu sistem projenin sıfır harici Python bağımlılığı kuralını korur; standart Python 3.11+ ve `sqlite3` üzerinde çalışır.

---

## 2. Mimari ve Veri Şeması

### 2.1 SQLite FTS5 Sanal Tablosu
`state_dir/memory.sqlite3` veritabanında mevcut tablolara ek olarak aşağıdaki sanal tablo oluşturulur:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
    id UNINDEXED,
    type,
    project,
    text,
    facts,
    tokenize='unicode61 remove_diacritics 2'
);
```

* **`id UNINDEXED`**: Ana `records(id)` anahtarıdır. Ters indekse eklenmez, sonuçları `records` tablosuna bağlar.
* **`type` ve `project`**: Tip ve proje bazlı hızlı arama/filtreleme sağlar.
* **`text` ve `facts`**: Tam metin aramasının gerçekleştirildiği alanlar.
* **`tokenize='unicode61 remove_diacritics 2'`**: Türkçe ve aksanlı karakterleri normalize ederek doğru eşleşme sağlar.

### 2.2 İşlem Bütünlüğü (Atomic Transactions)
Mevcut `BEGIN IMMEDIATE` işlem döngüsü içinde FTS senkronizasyonu korunur:
* `MemoryStore.ingest(record)`: `records` ve `events` yazılırken aynı transaction içinde `records_fts` tablosuna da eklenir.
* `MemoryStore.update_task(id, expected_revision, changes)`: Güncelleme anında `records_fts` tablosundaki eski girdi silinip yenisi eklenir.
* **Otomatik İndeks Kurulumu (Rebuild/Migration):** `MemoryStore.__init__` veya bağlantı anında `records_fts` boş veya eksikse, mevcut `records` tablosundaki kayıtlar okunarak FTS tablosu otomatik doldurulur.

---

## 3. API ve Tip Filtreleme (Type-Based Filtering)

### 3.1 Sabitler ve Doğrulama
`beyin_v3.py` içinde tanımlanan tipler:
```python
VALID_MEMORY_TYPES = ('episodic', 'semantic', 'procedural')
```
* `MemoryStore._validate(record)`: Eğer kayıtta `type` alanı varsa bu değerin `VALID_MEMORY_TYPES` içinde olduğunu denetler.

### 3.2 `retrieve` ve `_retrieve` İmzası
```python
def retrieve(self, query, project=None, audience="internal", statuses=None,
             limit=5, budget_chars=8000, snapshot=False, strict=False,
             candidate_only=False, types=None):
```

* `types=None`: Geriye dönük %100 uyumlu; filtre uygulamaz, tüm kayıtlar döner.
* `types="procedural"`: Otomatik olarak `["procedural"]` listesine çevrilir.
* `types=["semantic", "procedural"]`: Belirtilen tipler kümesindeki kayıtları kabul eder.
* Geçersiz tip: `ValueError("invalid memory type")` üretir.
* **Aday Filtresi:** `eligible` kayıtlar seçilirken `types` filtresi ön eleme (pre-filter) olarak işletilir.

---

## 4. Sıralama ve Birleştirme (BM25 + RRF)

### 4.1 FTS5 BM25 Arama
Aday kayıtlar arasından FTS5 sorgusu işletilerek BM25 sıralaması elde edilir:
```sql
SELECT id FROM records_fts WHERE records_fts MATCH ? ORDER BY bm25(records_fts)
```

### 4.2 Pluggable Vektör Arayüzü
`MemoryStore` üzerinde `semantic_searcher = None` kancası bulunur. Harici/yerel bir sağlayıcı verildiğinde:
```python
semantic_ranked = self.semantic_searcher(query, eligible_records)
```
Tanımlı değilse `semantic_ranked = []` kabul edilir.

### 4.3 Reciprocal Rank Fusion (RRF)
$k=60$ sabiti kullanılarak doküman skorları hesaplanır:
$$\text{RRF}(d) = \sum_{m \in M} \frac{1}{60 + r_m(d)}$$
* Vektör motoru yokken leksikal BM25 sırası doğrudan korunur.
* Vektör motoru varken her iki alanda da yüksek çıkan dokümanlar en üste taşınır.
* Eşit skor durumunda `updated_at` ve `id` ile sıralama korunur.
* Otomatik per-turn hook'ları için `strict=True` koruması ve bütçe (`budget_chars`) sınırları RRF sonrası aynen uygulanır.

---

## 5. Test Stratejisi ve Doğrulama

### 5.1 Mevcut Testlerin Güncellenmesi
* `tests/v3_turkish_test.py`: Veritabanındaki tablo listesini kontrol eden test (`tables - {'sqlite_sequence'}`), FTS5 sanal tablosunun oluşturduğu tabloları (`records_fts`, `records_fts_data`, `records_fts_idx`, `records_fts_config`, `records_fts_docsize`) hesaba katacak şekilde güncellenir.

### 5.2 Yeni Test Paketleri
1. **`tests/v3_memory_types_test.py`:**
   - Tip doğrulama (`VALID_MEMORY_TYPES`).
   - Tekil tip filtreleme (`types='procedural'`).
   - Çoklu tip filtreleme (`types=['semantic', 'procedural']`).
   - Geriye uyumluluk (`types=None`).
   - Geçersiz tip durumunda `ValueError`.
2. **`tests/v3_fts5_test.py`:**
   - Şema otomatik oluşturma ve yaşam döngüsü (`ingest`, `update_task`).
   - Kod sembolleri ve hata kodları tam eşleşmesi (`StripeWebhookHandler`, `ERR_401`).
   - Türkçe karakter normalizasyonu.
   - Eski veritabanından FTS tablosuna otomatik geçiş (migration).
3. **`tests/v3_rrf_hybrid_test.py`:**
   - Saf BM25 sıralaması koruma.
   - Mock semantik arayıcı ile RRF füzyon testi.
   - Bütçe kırpma (`truncated`, `budget_chars`) bütünlüğü.

---

## 6. Kabul Kriterleri
1. `tests/v3_memory_types_test.py` %100 başarılı.
2. `tests/v3_fts5_test.py` %100 başarılı.
3. `tests/v3_rrf_hybrid_test.py` %100 başarılı.
4. Tüm mevcut testler (`python3 -m unittest discover tests`) hatasız geçmeli.
