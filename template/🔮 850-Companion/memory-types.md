---
{"type": "semantic", "project": "Beyin", "visibility": "internal", "title": "Memory Types", "created": "{{TODAY}}", "updated": "{{TODAY}}", "tags": ["memory", "types", "classification"]}
---
# Memory Types

Bu belge Beyin v3 hafıza sisteminde kullanılan üç temel memory type'ını tanımlar. Her not, görev veya kayıt **tek bir** type alır: `episodic`, `semantic`, veya `procedural`.

## Type Tanımları

### episodic — Zaman Serisi / Anılar
**Ne:** Belirli bir zaman diliminde ne oldu, kim ne yaptı, hangi karar alındı.
**Örnekler:**
- `Journal.md` — ortak çalışma gözlemleri, öğrenimler
- `Threads.md` — aktif/kapalı konular, süregelen işler
- `Last-Session.md` — son oturum sonucu, açık adımlar
- `daily/v3/*.md` — günlük oturum logları
- Receipt'ler (oturum sonuçları)

**Retrieval filtresi:** `"Dün ne konuştuk?", "Son oturumda ne karar verdik?", "Bu konu hakkında geçmişte ne oldu?"`

### semantic — Kalıcı Bilgi / Gerçekler / Kimlik
**Ne:** Zamanla değişmeyen veya nadiren değişen, sorgulanabilir gerçekler, kimlik, tercihler.
**Örnekler:**
- `Core.md` — companion kimliği, kullanıcı ismi, hitap, çalışma alanı
- `knowledge/concepts/*.md` — kavram tanımları, teknik kararlar
- `knowledge/index.md` — kavram indeksi
- Proje yapılandırması, mimari kararlar

**Retrieval filtresi:** `"Ahmet'in hitabı nedir?", "Bu projenin mimarisi nasıl?", "Hangi kutuphane kullanıyoruz?"`

### procedural — Nasıl Yapılır / Kurallar / Playbook'lar
**Ne:** Süreçler, kurallar, workflow'lar, "nasıl" talimatları.
**Örnekler:**
- `Kurallar.md` — kullanıcı düzeltmeleri, çalışma kuralları
- `.agents/skills/*/SKILL.md` — skill talimatları
- `knowledge/playbooks/*.md` — tekrar eden işlemlerin adım adım rehberi
- CI/CD pipeline kuralları, code review checklist'leri

**Retrieval filtresi:** `"Not nasıl alınır?", "Receipt formatı nedir?", "Bu skill nasıl kullanılır?"`

## Kullanım Kuralları

1. **Tek type per dosya** — Bir dosya hem `semantic` hem `procedural` olmaz. Karma içerik ayrı dosyalara bölünür.
2. **Frontmatter zorunlu** — `note-create` ve `task-create` çağrılarında `metadata.type` alanı zorunludur.
3. **Retrieval'da filtre** — Context sorgularında `type` filtresiyle ilgili kayıtlar hızlı bulunur.
4. **Consolidation stratejisi** — AutoDream-lite consolidation her type için farklı prune/merge kuralları uygular:
   - `episodic`: Eski oturumlar özetlenir, detaylar arşivlenir
   - `semantic`: Çelişkiler çözülür, güncel gerçekler korunur
   - `procedural`: Eskimiş workflow'lar güncellenir, best practice'ler birleştirilir

## Validation

```python
# beyin_v3_sync.py içinde
valid_types = ('episodic', 'semantic', 'procedural')
if 'type' in metadata and metadata['type'] not in valid_types:
    raise ValueError('metadata.type must be episodic|semantic|procedural')
```

`type` vermek zorunlu değildir; yazılmayan kayıtlar tiplendirilmemiş sayılır ve
sezgisel filtreleme bunları asla elmez. Verildiğinde ise geçerli bir tip olmalıdır.

## İlgili Kaynaklar

- `beyin_v3_sync.py` — note_create/task_create validation
- `.agents/skills/beyin/SKILL.md` — type kullanımı
- `Core.md` (type: semantic), `Kurallar.md` (type: procedural), `Journal.md/Threads.md/Last-Session.md` (type: episodic)