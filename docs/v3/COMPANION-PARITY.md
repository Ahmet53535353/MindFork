# V2 → V3 kişilik ve süreklilik incelemesi

İnceleme tarihi: 2026-09-17. Karşılaştırılan tabanlar: V2 `2e074cc`, yayımlanmış
V3.0.2 `55cd4e8`. Kullanıcının aktardığı “kişilik/performans azaldı” geri bildirimi
bir kullanıcı gözlemidir. Aşağıdaki nedenler koddan doğrulanır; öznel kişilik puanı
veya tüm modeller için kalite artışı ölçülmüş değildir.

## Kayıp nerede oluştu?

| Davranış | V2 | V3.0.2 | Bu düzeltme |
| --- | --- | --- | --- |
| Kimlik kurulumu | Kişiselleştirilmiş CLAUDE ve Companion şablonları | ZIP installer yalnız teknik AGENTS/CLAUDE bloğunu kuruyordu; Core ve ilişki dosyaları oluşturulmuyordu | Ortak düşünme ortağı protokolü ve bir kez oluşturulan kullanıcıya ait başlangıç notları |
| Oturum açılışı | Core okuma talimatı ve deterministik ilişki köprüsü; üst sınır 16.000 karakter | Toplam 5.000 karakter; Core/Soul öncelikli sette yok; yinelenen JSON metadata bütçeyi tüketiyor | Core/Soul, düzeltmeler, son sonuç, aktif konu gövdeleri, son Journal ve bilgi haritası kısa kaynak bölümleriyle taşınıyor |
| “Beni tanıyor musun, nerede kalmıştık?” | İlişki kaynakları açılışta vardı | Sorgudaki kelimeler notla örtüşmüyorsa boş arama sonucu | İlişki sorularında deterministik companion bağlamı; genel arama sözleşmesi korunuyor |
| Journal ve Threads seçimi | Son Journal girişi; ancak Threads yalnız başlık/durum ve 12 satırdı | Journal dosya sonundan kırpılıyor; yeni kayıt en üstteyse kaybolabiliyor; kapalı konular bütçe tüketiyor | En yeni tarihli Journal, aktif Threads gövdesi; kırpma açık ve dosya yoluyla gösteriliyor |
| İlişkiden öğrenme | Core/Journal/Threads/Last-Session/Kurallar açıkça ajanın sorumluluğuydu | beyin skill'i ağırlıklı olarak görev/receipt işlemlerini anlatıyordu | Açık kullanıcı düzeltmesi, gerekçe, açık kalan adım ve anlamlı gözlem için somut yazım protokolü |
| Bilgi damıtma | Model compiler kavram, bağlantı ve bilgi indeksi üretiyordu | Compiler emekli edildi; receipt indeksi üretiliyor, sentez talimatı çok kısaydı | Aktif ajan için kavram/bağlantı/indeks güncelleme akışı; ayrı model çağrısı yok |

Kaynaklar: `scripts/install_v3.py`, `template/CLAUDE.md`,
`template/.claude/hooks/session-start.sh`, `template/.claude/scripts/compile.py`,
`template/.claude/scripts/beyin_v3_hook.py`, `template/.agents/skills/beyin/SKILL.md`.

[Issue #27](https://github.com/avenoxai/avenoxbeyin/issues/27) boş SessionStart sorgusunda
ilişki kaynaklarının seçilmediğini doğrudan raporladı. Önceki #29 düzeltmesi dört dosyayı
önceliklendirdi ama Core/Soul ve eksik kurulum/öğrenme protokolünü tamamlamadı.
[Issue #21](https://github.com/avenoxai/avenoxbeyin/issues/21) ise V2'nin Threads gövdesini
kaybettiğini gösterir: V2'nin hatalı satır filtresi geri getirilmedi. Windows hook
arızaları da algılanan unutkanlığa katkı yapmış olabilir; bunlar V3.0.2'de ayrı olarak
düzeltildi. Yeni [#32](https://github.com/avenoxai/avenoxbeyin/issues/32) raporu V3.0.1
kurulumunu anlatır; V3.0.2'de tekrar üretildiği varsayılmadı.

## Kurulum ve veri koruması

`beyin_v3_companion.py` pakete dahil edilir. Temiz installer eksik başlangıç notlarını
bir kez oluşturur. V2 veya V3'ten yönetilen güncellemede yeni worker ilk çalışmada aynı
kontrolü yapar. Önce mevcut Companion/Echo dizini, yoksa tek yerel Core/Soul dizini
kullanılır; birden fazla kimlik adayı varsa seçim uydurulmaz. Arşiv ve symlink dizinleri
kimlik olarak keşfedilmez. Kullanıcının Soul dosyası varsa rakip bir Core oluşturulmaz.

Başlangıç notları paket manifestinin yönetilen dosyalarına eklenmez. Kişisel değişiklikler,
güncelleme ve rollback/uninstall sonrasında kalır. Bir kez başlatıldıktan sonra kullanıcının
sildiği notlar yeniden yaratılmaz. Başlatma işareti yalnız dış yerel runtime state'indedir.
Öğrenme ve ilişki yazımları aktif ajan tarafından yapılır; worker kullanıcı geçmişi uydurmaz.

Normal 5.000, Ekonomik 2.000 karakter sınırı ve kayıtlı tercihler korunur. Daha az
bağlamda bütün dosyanın sığacağı iddia edilmez: kırpılan kaynağa okuma işareti eklenir.
Private/untrusted ve indekslendikten sonra değişmiş kayıtlar otomatik bağlamdan dışlanır.
`no_memory` olayları bağlam enjekte etmez ve kuyruğa yazılmaz.

Bütçe paylaşımı ([#45](https://github.com/avenoxai/avenoxbeyin/issues/45)): `Kurallar.md`
ve `Last-Session.md` eşit paylaşımdan önce bir taban pay alır; kurallar dosyası sığmadığında
yalnız sonu değil, başı ve sonu birlikte gelir ve aradaki işaret kaç karakterin atlandığını
ve dosyayı okumak gerektiğini söyler. Kesme satır sınırındadır, yarım kural gelmez. Bilgi
haritası ve ilişkili kaynaklar payını aldıktan sonra artan bütçe kırpılmış companion
bölümlerine geri verilir; sınır hiçbir durumda aşılmaz.

## Doğrulama

`tests/v3_companion_test.py` sentetik verilerle temiz ZIP kurulumu, üç istemcide aynı
bağlam, Normal/Ekonomik/alt sınır bütçeleri, ilişki sorusu, yanlış kimlik/arşiv ayrımı,
private/untrusted/değişmiş kaynaklar, büyük ve yeni-giriş-üstte Journal, bilgi haritası,
güncelleme/rollback koruması ve tek seferlik başlangıç davranışını sınar.

İlk sekiz regresyon senaryosu aynı dosyayla yayımlanmış `v3.0.2` üzerinde çalıştırıldı:
7 başarısız, 1 başarılı. Düzeltmede sekizi de geçti. Son genişletilmiş companion paketi
13/13 geçti. Eski sürümün başarısızlıkları özellikle eksik Core/kimlik, 2.000 karakterde
kaybolan bağlam, boş ilişki sorgusu ve no-memory ihlalini görünür kıldı.

Yerel tam suite 199/199, bunun içindeki V3 suite 152/152 geçti. Donmuş semantik sözleşme
development 10/10 ve holdout 6/6 olarak korundu. Gerçek V3.0.2 kodundan kurulmuş eski
güncelleyiciyle yerel `3.0.3` aday ZIP'ine geçiş, ilk worker'da eksik notların başlatılması,
hook'tan kimlik geri okuma ve 3.0.2'ye rollback sırasında kişisel notların korunması geçti.
Bu aday paket test sürümüdür; yayımlanmış release iddiası değildir.

```sh
python3 -m unittest discover -s tests -p 'v3_companion_test.py'
python3 -m unittest discover -s tests -p 'v3_*test.py'
python3 scripts/evaluate_v3.py
# Aynı regresyonları açılmış eski checkout üzerinde çalıştırmak için:
BEYIN_TEST_REPO=/path/to/v3.0.2 python3 tests/v3_companion_test.py
```

Bunlar kaynak aktarımı, kurulum ve koruma sözleşmelerinin testleridir. Yeni canlı model
konuşmalarında kişilik kalitesi için kör kullanıcı karşılaştırması yapılmadı. Öğrenme
protokolünün uygulanması aktif ajanın talimat takibine bağlıdır; mevcut hafıza verisi
otomatik olarak geriye dönük yeniden yazılmaz.
