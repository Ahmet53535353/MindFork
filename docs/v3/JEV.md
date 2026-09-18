# İsteğe bağlı Jev danışmanı

Normal `context`, lifecycle hook'ları ve otomatik işler yerel kalır. Bu eklenti **varsayılan kapalıdır**. Jev bellek kaydetmez, kullanıcı onayı vermez veya kaynak/proje sınırını genişletmez.

## Açık etkinleştirme

CLI'nin `--state` ile kullandığı kasa dışındaki dizine `jev.json` koyun:

```json
{"mode":"shadow","model":"jev-1.13.0","provider":"typesafe","timeout":3,"max_candidates":32,"max_questions":96,"max_input_chars":24000,"cache_ttl":3600}
```

`TYPESAFE_API_KEY` ortam değişkeninde olmalıdır. Anahtarı Markdown'a, sürüm kontrolüne veya komut argümanına yazmayın. `env_file` kullanılırsa mutlak yol gerekir. Sağlayıcı URL'si `base_url` veya `TYPESAFE_BASE_URL` ile seçilir; HTTPS ve yerel HTTP desteklenir. Vercel uyumlu bir köprü kullanılıyorsa `provider: "vercel"` seçilebilir; bu bir Vercel hesap/anahtar kurucusu değildir.

```sh
python scripts/beyin_v3.py --vault /path/to/vault --state /path/to/state context "kısa notlar" --project demo --jev
```

Kurulu kasada karşılığı: `python beyin.py context "kısa notlar" --project demo --jev --json`. `--json`, danışman teşhislerini de gösterir. İnceleme için `python beyin.py jev-review --project demo --file proposal.json --json` kullanın.

`--jev` ve açık proje kimliği birlikte gerekir. Bu çağrı sorguyu ve yerel aramanın seçtiği en fazla belirtilen sayıdaki kayıt metnini sağlayıcıya gönderir. `internal` görünürlük de gönderilebilir; yalnız kamu metni için `--audience public` kullanın. `private`, kapsam dışı, güvenilmeyen, değişmiş ve superseded kayıtlar gönderilmez. Yerel sır örüntüsü eşleşirse çağrı yapılmaz; örüntü taraması tüm hassas bilgileri tanıma garantisi değildir.

- `off`: ağ/anahtar/cache erişimi yok.
- `shadow`: puanlar `jev` alanında; yerel sonuç ve sıralama korunur.
- `on`: yalnız zaten teslim edilen aynı kayıt kümesi sıralanır. Yeni kayıt seçilmez, karakter bütçesi değişmez. Kelime aramasının kaçırdığı kaydı bulma iddiası yoktur.

Çağrıdan sonra kaynak hashleri, indeks revizyonları ve erişim koşulları yeniden kontrol edilir. Değişim varsa puan atılır ve güncel yerel sonuç kullanılır. Timeout, 429, eksik anahtar veya bozuk yanıt yerel sonuçları engellemez. Teşhislerde ham servis hataları bulunmaz.

## Kaydedilmemiş bilgi adayını inceleme

Önce normal `context` ile kaynak kaydının `id` ve `source_sha256` değerlerini alın. Ayrı bir JSON dosyası hazırlayın:

```json
{
  "status":"proposed",
  "project":"demo",
  "claim":"Demo projesinde kısa notlar tercih ediliyor.",
  "evidence":[{
    "record_id":"demo-notlar",
    "source_sha256":"KAYNAK_DOSYANIN_GUNCEL_SHA256_DEGERI",
    "quote":"Demo için kısa notlar kullanalım."
  }]
}
```

```sh
python scripts/beyin_v3.py --vault /path/to/vault --state /path/to/state jev-review --project demo --file proposal.json
```

1–8 kanıt, tam alıntı, aynı proje ve güncel hash zorunludur; alıntı hem indeks metninde hem gerçek kaynakta bulunmalıdır. Kaynak senkronizasyonu eksikse inceleme durur. Yanıt her zaman `approved: false`, `memory_written: false` içerir. Sonuç yalnız iddianın alıntıyla desteklenme puanıdır; başka kartlarla otomatik birleştirme/çelişki çözümü yapmaz. Ayrı inceleyen kişi/ajan kapsam ve zaman sınırını değerlendirir, gerekirse mevcut `note-create` akışını kullanır.

## Aktarılan çözümler ve ölçüm

Forn Hafıza OS `524fd07` sürümünden bütçeli istemci, kaynak/scope bağlı puan önbelleği, strict skor doğrulaması ve Vercel'in iki ondalığa yuvarlanmış olasılıkları için dar tolerans aktarıldı. Tolerans yalnız Vercel'de matematiksel olarak mümkün dağılımlara uygulanır; doğrudan TypeSafe doğrulaması gevşetilmez. MIT atfı istemcinin içinde ve [lisans dosyasında](THIRD-PARTY-JEV.txt) bulunur.

Önbellek yalnız doğrulanmış puanları ve sınırlı metaveriyi state dizininde saklar; sorgu, kaynak metni ve anahtar saklamaz. Cache anahtarı kaynak sürümü, proje, amaç, model, endpoint ve rubriğe bağlıdır. Token sayaçları sağlayıcıdan gelirse raporlanır; karakter bütçesi token/fatura değildir. İstemcide özel 400 çağrı sınırı yoktur; önceki deney köprüsünün sayacı sağlayıcı hesap kotası değildi.

Öğrenme değişikliklerini ölçerken kaynakları ve soruları yazımdan önce dondurun. Aynı kod/yönlendirmeyle önce/sonra nihai bağlam teslimini ve proje dışına taşmayı ölçün; model açık/kapalı karşılaştırmasını ayrı yapın. Özel kasadaki kartlar ve deney sonuçları bu depoya taşınmadı. Buradaki sentetik offline testler genel anlamsal başarı veya canlı Jev bağlantısı kanıtı değildir.
