# İsteğe bağlı Jev danışmanı

Normal `context`, lifecycle hook'ları ve otomatik işler yerel kalır. Bu eklenti **varsayılan kapalıdır**. Jev bellek kaydetmez, kullanıcı onayı vermez veya kaynak/proje sınırını genişletmez.

## Açık etkinleştirme

Kurucu bu eklentiyi sormaz ve kurmaz. Açmak, kapatmak ve durumu görmek için kurulu kasada:

```sh
python beyin.py jev status
python beyin.py jev shadow
python beyin.py jev on
python beyin.py jev off
```

Kaynak depodan aynı komut: `python scripts/beyin_v3.py --vault /path/to/vault --state /path/to/state jev status`.

`status` yalnız okur; `off|shadow|on` ayarı yazıp sonucu ve `"changed": true` döndürür. Komut kasa indeksine veya kaynak senkronizasyonuna ihtiyaç duymaz. Anahtar kabul etmez ve yazdırmaz; `--key` benzeri bir seçenek bilerek yoktur.

Özellikler ayrı ayrı açılıp kapanır; `--enable` ve `--disable` tekrarlanabilir ve `status` ile birlikte kullanılamaz:

```sh
python beyin.py jev on --enable auto_context
python beyin.py jev shadow --disable answer
```

| Özellik | Kullanan komut | Varsayılan |
| --- | --- | --- |
| `context` | `context --jev` | açık |
| `review` | `jev-review` | açık |
| `answer` | `jev-answer` | açık |
| `auto_context` | her turdaki hook yolu; ayrı bir çalışma, açıkça etkinleştirilmedikçe kapalı | kapalı |

Kapalı bir özelliğin amacı çağrılırsa istemci anahtar okumadan ve ağa çıkmadan `off` modu ile `feature_disabled` teşhisi döndürür.

`auto_context` açıkken `status` çıktısında `automatic_model_calls: true` olur; komut buna, her turda istemin ve eşleşen `internal`/`public` not alıntılarının sağlayıcıya gittiğini söyleyen bir `notice` ekler. `private` notlar gönderilmez. Mod `off` değilken anahtar yoksa `warning` eklenir ve çağrılar yerel sonuca düşer.

### Acil kapatma

`BEYIN_JEV_DISABLE=1` ortam değişkeni veya state dizinindeki `jev.disabled` dosyası, kayıtlı modu değiştirmeden çağrıları durdurur. `status` bu durumda `mode: "off"`, eski değeriyle `saved_mode` ve `kill_switch: true` gösterir. Değişken kaldırılınca veya dosya silinince kayıtlı moda dönülür.

### Çağrı kaydı

Her çağrı state dizinindeki `jev-calls.jsonl` dosyasına tek satırlık sayaç yazar: amaç, mod, önbellek isabeti, `degraded`, hata kodu, gecikme, giriş token sayısı ve zaman. Sorgu metni, aday metni, yanıt içeriği ve anahtar yazılmaz. Dosya sınırı aşarsa eski yarısı atılır. `jev status` ve `doctor` son 24 saati buradan özetler.

### Elle düzenleme

`jev.json` hala elle düzenlenebilir; `timeout`, `max_candidates`, `base_url`, `env_file` gibi ileri anahtarlar komut yazarken korunur. Komut bu dosyanın tek yazıcısıdır: 0600 izinle atomik yazar. Dosya bozuksa komut hata döndürür ve dosyaya dokunmaz.

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

## Cevaptaki iddiaları kaynaklarıyla denetleme

`jev-answer`, hazırlanmış bir cevaptaki 1–20 iddiayı ayrı ayrı değerlendirir.
Forn Hafıza OS yerel `jev_answer.py` akışındaki kaynak kapısı ve destek/çelişki
ayrımı V3 kayıt kimliği, proje kapsamı ve revizyon sözleşmesine uyarlandı.
Kişisel kayıtlar ve diğer hafıza sistemi güncellemeleri aktarılmadı.

Önce `context` çıktısından kayıt kimliğini ve güncel hash'i alın. `claims.json`:

```json
[
  {
    "text": "Demo projesinde kısa notlar tercih ediliyor.",
    "citations": [
      {
        "record_id": "demo-notlar",
        "source_sha256": "KAYNAK_DOSYANIN_GUNCEL_SHA256_DEGERI",
        "quote": "Demo için kısa notlar kullanalım."
      }
    ]
  }
]
```

```sh
python beyin.py jev-answer --project demo --file claims.json --json
```

Kaynak depodan kullanım:

```sh
python scripts/beyin_v3.py --vault /path/to/vault --state /path/to/state jev-answer --project demo --file claims.json
```

İddia başına en fazla 8 atıf, toplam 32.000 giriş karakteri kabul edilir.
İddialar sağlayıcıya 8'li paketlerle gider (aynı anda en fazla 4 istek). Paket
içinde her iddia kendi anahtarıyla durur (`items.k3`) ve sorusu o yolu
backtick içinde adresler; liste sırası ve dolaylı atıfla adreslemede canlı
Jev'de puanlar komşu iddialara sızıyordu. Bir paket `max_input_chars` sınırını
aşarsa ağ çağrısı yapılmadan ikiye bölünür. Hata veren bir istek yalnız kendi
paketindeki iddiaları `degraded` yapar.

Alıntıyla birlikte kaynak kaydında alıntının iki yanındaki en fazla 400'er
karakter de gönderilir (iddia başına toplam 4.000 karakter). Alıntı birebir
doğru olup notun devamı tersini söyleyebilir ("eski plan ... bu plan iptal
edildi"); yalnız alıntı gönderildiğinde böyle iddialar `supported` çıkıyordu.
Bu pencere de aynı sır taramasından geçer; eşleşme varsa o iddia gönderilmez ve
`context_sensitive` ile `degraded` olur.

Boş atıf veya eşleşmeyen hash/alıntı `insufficient` döndürür ve o iddia
sağlayıcıya gönderilmez. Alıntı hem indeks kaydında hem gerçek kaynakta aynen
bulunmalıdır. Diğer Jev komutlarındaki proje, görünürlük, güven ve sır
kontrolleri geçerlidir. Bu açık komut `internal` kayıt alıntılarını ve çevresindeki
metni sağlayıcıya gönderebilir; `private` kayıtlar elenir. Normal bağlam ve hook akışı değişmez.

`mechanical_verified`, yalnız çağrı öncesindeki kaynak/alıntı eşleşmesini
bildirir; anlamsal doğrulama değildir. `off` ve `shadow` modlarında anlamsal
sonuç `uncertain` kalır. `on` modunda her iddia için tek bir seçim sorusu
sorulur: kanıt iddiayı destekliyor mu, iddiayla çelişiyor mu, yoksa iddia
hakkında bir şey söylemiyor mu. Bu, sağlayıcının kendi atıf denetimi tarifidir.

| Seçim | Güven ≥ 0,8 | Güven < 0,8 |
|---|---|---|
| `supports` | `supported` | `uncertain` |
| `contradicts` | `contradicted` | `uncertain` |
| `says_nothing` | `insufficient` | `uncertain` |

Sonuçta `relation` ve `confidence` alanları da döner; `uncertain` sonuçlarda
teşhis `low_confidence` olur. Güven, sağlayıcının seçenek olasılıklarından
türettiği değerdir; doğruluk olasılığı değildir.

0,8 eşiği sağlayıcı tarifindeki başlangıç değeridir; kalibre edilmiş doğruluk
olasılığı veya genel başarı ölçümü değildir. Çağrıdan sonra
kaynak, indeks revizyonu, erişim koşulları veya yapılandırma değişirse sonuç
`degraded` olur. Servis hataları da doğrulanmış sonuç üretmez. Komut cevabı
yeniden yazmaz, aday onaylamaz veya kanonik hafıza kaydı oluşturmaz;
`approved`, `memory_written` ve `rewrites` daima `false` olur. CLI'nin normal
kaynak senkronizasyonu yerel indeksi yenileyebilir; Jev puan önbelleği de
state dizininde güncellenebilir.

Testler sentetik kaynaklar ve offline transport ile çalışır. Tasarım
2026-09-20'de canlı `jev-1.13.0` üzerinde 26 sentetik Türkçe/İngilizce iddiayla
(olumsuzluk eki, farklı sayı/gün, kapsam genişletme, ilgisiz alıntı, birebir
alıntı ama notun devamı tersini söylüyor) seçildi. Uçtan uca, iki sıralama ve
üçer tekrarla 156 sonuç: 138 beklenen net etiket, 18 `uncertain`, yanlış net
etiket yok; 26 iddia 4 istek ve iddia başına yaklaşık 250 giriş token'ı. İki
Score sorulu ve yalnız alıntı gönderen önceki hal iddia başına yaklaşık 750
token harcıyor ve iptal edilmiş plandan alıntı içeren 4 iddianın 3'ünü
kaçırıyordu. Paketleme bedelsiz değildir: zor iddialar paketin sonlarında
güven kaybedip `uncertain` olabiliyor (iddia başına tek istekte 24/24, pakette
18-21/24). Bu küçük bir yapılandırma denemesidir; gerçek kasalarda genel
doğruluk, maliyet avantajı veya kullanıcı kabulü iddia edilmez.
