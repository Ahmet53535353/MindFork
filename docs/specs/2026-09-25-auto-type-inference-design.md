# Otomatik Tip Sezgisi (Auto Type Inference) — Tasarım ve Uygulama Planı

Tarih: 2026-09-25 · Dal: feat/explicit-memory-typing · Durum: ONAYLANDI

## Amaç

`MemoryStore.retrieve()` çağrısında `types` açıkça belirtilmemişse, sorgunun
niyetinden (episodic / semantic / procedural) hangisinin arandığını sezgisel
olarak tahmin edip tip filtresini otomatik uygulamak. Makale karşılığı:
Context Hydration'da tür karışmasının (episodik sohbet kırıntısının kalıcı
karar sanılması) önlenmesi.

## Kararlar (nihai)

1. **Muhafazakâr, tamamen Türkçe ipucu listesi** (kullanıcı kararı): yalnızca
   çok belirgin ifadeler filtre tetikler; İngilizce sorgular sezgisiz kalır
   (filtresiz = güvenli eski davranış).
2. **Tek-küme kuralı:** tam olarak bir ipucu kümesi eşleşirse filtre uygulanır;
   sıfır veya ≥2 küme eşleşirse `None` → tüm tipler taranır.
3. **Override:** açık geçen `types` (str veya list) sezgiyi tamamen atlar.
4. **Kapsam:** `_retrieve` içinde yalnız `types=None` passedığında uygulanır.
   `query=''`, snapshot ve scoped-listing yolları fiilen etkilenmez (boş
   sorguda eşleşme zaten yoktur).
5. **Stem uyumu:** ipucu kümeleri STOPWORDS deseniyle modül yüklemede
   `_tokens`'tan geçirilir; sorgu tarafı da aynı huniden geçtiği için Türkçe
   katlama/kök sorunu yaşamaz. Türkçedeki kök allomorf boşlukları
   (kaldık/kalmıştık, konuşma/konuşmuştuk) ipucu dizisine yüzey varyantları
   eklenerek kapatılır; `_tokens` bunları kök kümesine çevirir.

## API (beyin_v3.py)

```python
EPISODIC_CLUES = _tokens("dün oturum sefer görüşme görüşmüş konuştuk konuşmuştuk konuşma kaldık kalmıştık kalmış önceki geçen günlük hatırla hatırlıyorum")
PROCEDURAL_CLUES = _tokens("nasıl adım kural akış işlem prosedür kontrol listesi kurulum yayına")
SEMANTIC_CLUES = _tokens("karar mimari tanım kavram anlam neden fark belge")

def infer_types(query):
    """Tek küme eşleşirse ['<tip>'], şüphede (0 veya ≥2 küme) None döner."""
```

Bağlama: `_retrieve` başlangıcında `types is None` ise
`types = infer_types(query)`; sonrasında mevcut tip filtreleme aynen çalışır.

## Testler (tests/custom/v3_type_inference_test.py — TDD, önce Red)

| Test | Beklenti |
|---|---|
| `infer_types("dün nerede kalmıştık")` | `['episodic']` |
| `infer_types("deploy nasıl yapılır")` | `['procedural']` |
| `infer_types("mimari kararımız neydi")` | `['semantic']` |
| `infer_types("masa")`, `infer_types("")` | `None` |
| `infer_types("dün oturumda deploy adımlarını konuşmuştuk")` (episodik+prosedural çakışması) | `None` |
| Entegrasyon: karışık vault'ta `retrieve("dün ne konuştuk")` | yalnız episodik kayıt |
| Override: aynı sorguda `types="procedural"` | sezgi işlemez, prosedural gelir |
| Regresyon kilidi: `query=''` çağrısı | çıktı eskisiyle birebir |

## Uygulama sırası

1. Test dosyası (Red) → 2. `infer_types` + `_retrieve` bağlama (Green) →
3. custom testler → 4. tam regresyon (`python3 -m unittest discover tests
-p "*test.py"`); ipucu kelimesi içeren eski test sorguları kırılırsa ipucu
listesi daraltılır (liste daraltmak test gevşetmekten yeğdir) →
5. commit + push.

## Riskler

- Yanlış filtre → hedef notun elemeye takılması: tek-küme kuralı + BM25'in
  filtre-sonrası çalışması iki tampon.
- Stem çakışması: muhafazakâr liste + tam regresyon koşusu freni.
- Performans: üç küme-kesişimi, mevcut tokenizasyonun yanında ihmal edilebilir.
