# Uygulama Planı: Type-Based Retrieval ve Hybrid RAG (BM25 + RRF)

**Tarih:** 2026-09-25  
**Tasarım Referansı:** [`docs/specs/2026-09-25-hybrid-rag-type-retrieval-design.md`](file:///home/hayalet/Projects/feat-explicit-memory-typing-dev/docs/specs/2026-09-25-hybrid-rag-type-retrieval-design.md)  
**Metodoloji:** Test Driven Development (TDD) — Her adımda önce test, sonra kod, sonra doğrulama.

---

## Aşama 1: Tip Bazlı Getirme ve Doğrulama (Type-Based Filtering)

### Görev 1.1: Testlerin Yazılması (Red)
- **Dosya:** `tests/v3_memory_types_test.py`
- **İçerik:**
  - `_validate()` fonksiyonunda geçersiz tip verildiğinde `ValueError` fırlatılması.
  - `retrieve(..., types=None)` ile geriye dönük tam uyumluluk (tüm kayıtların gelmesi).
  - `retrieve(..., types='procedural')` ile sadece prosedürel notların çekilmesi.
  - `retrieve(..., types=['semantic', 'procedural'])` ile çoklu tip filtreleme.
  - `retrieve(..., types='invalid')` ile hata denetimi.

### Görev 1.2: Çekirdek Uygulama (Green)
- **Dosya:** `template/.claude/scripts/beyin_v3.py`
- **Değişiklikler:**
  - `VALID_MEMORY_TYPES = ('episodic', 'semantic', 'procedural')` sabitini ekle.
  - `_validate(record)` metodunda varsa `record['type']` alanını doğrula.
  - `_retrieve()` ve `retrieve()` imzalarına `types=None` parametresini ekle.
  - `eligible` kayıtlar seçilirken `types` filtresini uygula.

### Görev 1.3: Doğrulama
- `python3 -m unittest tests/v3_memory_types_test.py` çalıştırıp testlerin başarıyla geçtiğini doğrula.

---

## Aşama 2: SQLite FTS5 (BM25) Leksikal İndeksleme

### Görev 2.1: Testlerin Yazılması (Red)
- **Dosya:** `tests/v3_fts5_test.py`
- **İçerik:**
  - `records_fts` tablosunun otomatik oluştuğunun testi.
  - `ingest()` ile FTS tablosuna veri yazıldığının testi.
  - `update_task()` ile FTS tablosundaki verinin güncellendiğinin testi.
  - Kod sembolleri (`StripeWebhookHandler`, `ERR_401`), hata kodları ve Türkçe aksan normalizasyonunun BM25 ile tam eşleşme testi.
  - FTS tablosu olmayan eski veritabanlarının ilk açılışta otomatik migrate/rebuild edildiğinin testi.

### Görev 2.2: Mevcut Tablo Kontrol Testinin Güncellenmesi
- **Dosya:** `tests/v3_turkish_test.py`
- **Değişiklik:** SQLite'ın FTS5 sanal tablosu için açtığı tabloları (`records_fts`, `records_fts_data` vb.) tablo listesi karşılaştırmasında dikkate al.

### Görev 2.3: Çekirdek FTS5 Uygulaması (Green)
- **Dosya:** `template/.claude/scripts/beyin_v3.py`
- **Değişiklikler:**
  - `_init_database` veya tablo oluşturma adımında `records_fts USING fts5(...)` sanal tablosunu ekle.
  - Otomatik migration mantığı ekle (mevcut `records` tablosunda kayıt olup `records_fts` boşsa senkronize et).
  - `ingest()` ve `update_task()` metodlarında `records_fts` tablosunu `BEGIN IMMEDIATE` içinde güncelle.
  - `_retrieve()` içinde BM25 sorgusunu işletip leksikal sıralamayı üret.

### Görev 2.4: Doğrulama
- `python3 -m unittest tests/v3_fts5_test.py tests/v3_turkish_test.py` çalıştırıp doğrula.

---

## Aşama 3: RRF (Reciprocal Rank Fusion) ve Vektör Kancası

### Görev 3.1: Testlerin Yazılması (Red)
- **Dosya:** `tests/v3_rrf_hybrid_test.py`
- **İçerik:**
  - `_rrf_fuse(lexical_ids, semantic_ids, k=60)` matematiksel birleşim testi.
  - Semantik sıralayıcı yokken BM25 sırasının aynen korunması.
  - Sahte (mock) semantik sıralayıcı ile hem BM25 hem semantikte üstte olan kaydın 1. sıraya çıkması.
  - Bütçe sınırı (`budget_chars`) ve kırpma (`truncated`) mantığının RRF sonrası bozulmadığının testi.

### Görev 3.2: Çekirdek RRF Uygulaması (Green)
- **Dosya:** `template/.claude/scripts/beyin_v3.py`
- **Değişiklikler:**
  - `_rrf_fuse` yardımcı fonksiyonunu ekle.
  - `MemoryStore` sınıfına `semantic_searcher = None` kancası ekle.
  - `_retrieve()` akışını RRF ile birleşik sıralamayı kullanacak şekilde güncelle.

### Görev 3.3: Doğrulama
- `python3 -m unittest tests/v3_rrf_hybrid_test.py` çalıştırıp doğrula.

---

## Aşama 4: Genel Regresyon ve Entegrasyon Doğrulaması

### Görev 4.1: Tüm Test Paketinin Koşulması
- `python3 -m unittest discover tests` komutunu çalıştırarak tüm projenin sıfır hatayla geçtiğini doğrula.

### Görev 4.2: Değişikliklerin Commit Edilmesi
- Yeni testleri ve çekirdek kodları git'e düzenli ve açıklayıcı commit mesajıyla işle.
