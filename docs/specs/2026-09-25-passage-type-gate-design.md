# Passage Yoluna Tip Kapısı Devri (tasarım)

Tarih: 2026-09-25 · Dal: feat/explicit-memory-typing · Durum: ONAYLANDI, UYGULANIYOR
Önceki: `2026-09-25-hybrid-rag-implementation-record.md` (kalan işler madde 3),
`docs/v3/STRICT-PASSAGE-RAG.md` (#83), `2026-09-25-auto-type-inference-design.md` (yumuşak kapı).

## Problem

Tip sistemi yalnız not-level `retrieve()` yolunda çalışıyor. Tur-başı otomatik bağlam yolu
(`context_for` → `beyin_v3_passage.context_for`; çağıranlar: hook, companion, JEV) tip
bilgisini hiç görmüyor: ne açık `types` filtresi ne de sorgudan sezilen yumuşak kapı.
En sık çalışan getirme yolu, tip sisteminin en etkisiz olduğu yol.

Somut zarar: prosedür ipucu taşıyan bir sorguda, eski ve **etiketli** bir episodic kayıt
kelime örtüşmesiyle passage sıralamasına girip fair-share bütçesini yiyebiliyor; makalenin
"stale episodic floods procedural" derdi tur-başı bağlamda aynen sürüyor.

## Kısıt (tasarımı belirleyen)

Passage önbelleği havuz parmak izi (`pool`) + `block_df`/`source_df` istatistikleri üzerine
kurulu; FLOOR bu havuzda kalibre edildi. Tip filtresi **havuzda/index inşa aşamasında**
uygulanırsa her tipli sorgu ayrı parmak izi üretir → df sürekli yeniden hesaplanır (cache
thrash), idf ölçeği ve FLOOR kalibrasyonu bozulur.

## Tasarım

1. **Politika tek kaynak** (`beyin_v3.py`, modül düzeyi yardımcı işlevler):
   - `resolve_type_filter(query, types) -> (types_set, type_gate)`
     Açık `types` doğrulanır (str→list, VALID_MEMORY_TYPES, ValueError) → `(set, None)`.
     `types=None` ise `infer_types(query)` → `(None, küme|None)`.
   - `record_matches_types(record, types_set, type_gate) -> bool`
     Açık filtre katıdır (tipsiz deelenir); sezgisel kapı yumuşaktır
     (`type` yoksa kayıt kalır); ikisi de yoksa her şey geçer.
   - `_retrieve` bu ikisini kullanacak biçimde refactor edilir; **davranış birebir aynı**
     (mevcut 5 custom test dosyası bunu kilitler).
2. **`beyin_v3_passage.py`**:
   - `context_for(..., types=None)`: girdi doğrulamasından hemen sonra
     `resolve_type_filter` çağrılır (ValueError, index inşasından **önce** fırlar);
     `allowed = {id | record in candidates, record_matches_types(...)}` (kapı yoksa `None`).
   - `search(..., allowed=None)`: passage döngüsünde `allowed is not None and
     record["id"] not in allowed` → atla. Yalnız arama anında, O(1) küme sorgusu.
   - Index/cache **hiç değişmez**: aynı havuz, aynı df, aynı FLOOR. İki testle sabitlenir.
3. **Çağıranlar değişmez**: hook/companion/JEV `types` geçmez → sorgu sezgisinden yumuşak
   kapı otomatik etkin. Düşüş yolu (IndexPending → `shared_context` → `retrieve`) `types`
   kwargs'ını zaten kabul eder; geçiş şeffaf.

## Testler (önce kırmızı, `tests/custom/v3_passage_types_test.py`)

1. Yumuşak kapı passage'da: prosedürel ipuculu sorgu, çelişkili tipli kaydı eler; tipsiz kalır.
2. Açık `types` passage'da katı: yalnız tipliler; tipsiz deelenir.
3. Açık `types` sezgiyi ezer (prosedürel ipucu + `types="episodic"` → episodic gelir).
4. Geçersiz `types` → ValueError (index yokken de, index varken de).
5. Cache-değişmezliği: tipli ve tipsiz sorgular `passages.json` baytını değiştirmez.
6. Düşüş yolu: `strict=False` yerine normal `retrieve(types=...)` regresyonu yok.

## Kabul ve kapsam dışı

- Kapı yalnız **eleme** yapar; sıralama ağırlıkları, FLOOR, blok bölme dokunulmaz.
- JEV/cevaplayıcı davranışında ek değişiklik yok (kapıyı bedavaya alır).
- `snapshot_context` tip kapısı taşımaz (bağlantısız devralma, kapısız kalmaya devam eder).

## Uygulama sonucu

- `resolve_type_filter` + `record_matches_types` `beyin_v3.py`'de `infer_types` ardına eklendi; `_retrieve` bunları kullanıyor (davranış birebir aynı, eski custom testler geçiyor).
- `beyin_v3_passage.context_for` artık `types=None` alıyor (ValueError index inşasından önce), `search(allowed=)` yalnız arama anında eliyor; index/cache kodu değişmedi.
- Çağıranlar (hook/companion/JEV) değişmedi; sorgu sezgisinden yumuşak kapı tur-başı bağlamda otomatik etkin.
- TDD: kırmızı (1 FAIL + 4 TypeError, baseline yeşil) → yeşil; hedefli 47/47, tam paket: `docs/specs/2026-09-25-hybrid-rag-implementation-record.md` test listesine bakınız.
- Docs: PREFERENCES.md madde + RUNTIME.md cümle eklendi; record'da madde 3 kapatıldı.
