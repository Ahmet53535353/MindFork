# 🧠 avenoxbeyin V3

Claude Code, Codex veya Google Antigravity ile kullanabileceğin yerel ikinci beyin. Notların Markdown dosyalarında kalır; bir istemcide kaydettiğin kaynak ve iş sonucu diğerinde de bulunabilir. Obsidian ile açabilir, normal bir metin editörüyle düzenleyebilirsin.

Python **3.11 veya üzeri** yeterli. Git, pip, Mem0 hesabı, API anahtarı veya sürekli açık sunucu gerekmez. Kullandığın AI istemcisinin kendi kurulumu ve hesabı ayrı olarak gerekir.

> **V3.1.0:** Yeni sürüm bildirimi, tek komutla doğrulanmış güncelleme ve geri alma. V3.0.2 kullanıyorsan bir kez vault içinde `python3 beyin.py update` çalıştır; sonraki sürümleri oturum başında gör. [Sürüm notları](docs/v3/releases/3.1.0.md) · [Güncelleme rehberi](docs/v3/UPDATE.md).

## En kolay kurulum: bir klasör, bir mesaj

1. Obsidian'da yeni bir vault oluştur veya mevcut vault klasörünü seç.
2. Bu klasörü Codex, Claude Code veya Antigravity ile aç.
3. Aşağıdaki mesajı yapıştır:

> https://avenox.lol/beyin.md adresini oku. Bu klasöre ikinci beynimi kur. Mevcut kurulum varsa notlarımı koruyarak güncelle. Gerekli indirme ve kurulum adımlarını sen yap. Sonunda örnek bir bilgiyi kaydedip yeni oturumda geri okuyarak birlikte doğrulayalım.

Ajan resmi kararlı paketi bulur, checksum ile doğrular, geçici alanda açar, kurulumu yapar ve sağlık kontrolünü çalıştırır. Kullanıcı yalnızca istemcinin gösterdiği normal klasör, workspace veya hook güven incelemesini tamamlar.

Görsel anlatım, kopyalanabilir mesaj ve manuel indirme: **[avenox.lol/ikincibeyin](https://avenox.lol/ikincibeyin)**.

## Manuel kurulum

1. [V3.1.0 sürüm sayfasını](https://github.com/avenoxai/avenoxbeyin/releases/tag/v3.1.0) aç. **[beyin-v3-3.1.0.zip](https://github.com/avenoxai/avenoxbeyin/releases/download/v3.1.0/beyin-v3-3.1.0.zip)** dosyasını ve yanındaki SHA-256 dosyasını indir. GitHub'ın otomatik “Source code” arşivi yerine bu paketi seç.
2. Obsidian'da bir vault oluştur veya mevcut vault klasörünü seç. Notlarını başka yere taşıman gerekmez.
3. Açtığın paket klasöründe terminal aç ve vault yolunu kendi klasörünle değiştir:

macOS / Linux:

```sh
python3 scripts/install_v3.py --vault "/tam/yol/Beynim"
```

Windows:

```powershell
py -3 scripts/install_v3.py --vault "C:\Notlar\Beynim"
```

Kurulum üç istemci için proje bağlantılarını, ortak motoru, üç başlangıç skill'ini ve güncelleme kısayolunu kurar. Bundan sonra paket klasörünü açık tutman gerekmez.

Hermes Agent kullanıyorsan aynı motor bir Hermes eklentisi üzerinden bağlanır; installer eklenti dosyalarını vault içine yazar, ama profil bazlı bağlantı ve `hermes plugins enable beyin-v3` adımını sen yaparsın. Adımlar: [docs/v3/HERMES.md](docs/v3/HERMES.md). Bu destek V3.1.0 paketine dahildir.

Vault klasörünü kullandığın AI istemcisinde açıp **yeni bir oturum başlat**. Codex'te `/hooks` ekranında yeni hook tanımlarını inceleyip güven; diğer istemcilerde workspace güvenini tamamla. İstemci güvenini kurucu senin adına uydurmaz. Agent ile kurulum yapmak istersen [SETUP-V3.md](SETUP-V3.md) rehberini takip etmesini iste.

OpenCode için ek adım yok: installer vault içine eklentisini yazar, OpenCode vault klasöründe açılınca aynı motora bağlanır. Adımlar: [docs/v3/OPENCODE.md](docs/v3/OPENCODE.md).

## İlk konuşma

V3.1.0 kişilik/süreklilik davranışı: yeni kurulum düşünme ortağı kimliğini
ve başlangıç notlarını oluşturur; mevcut Core/Soul, kullanıcı düzeltmeleri, aktif konular
ve son oturum kaynakları açılışta önceliklidir. Kalıcı öğrenimler aktif ajan tarafından
kavram ve bağlantı notlarına işlenir. [V2/V3 karşılaştırması ve doğrulama](docs/v3/COMPANION-PARITY.md).
Bu davranış V3.1.0 paketine dahildir.

Ajanına şunu söyle:

> Beyin skill'ini kullan. Beni tanımak için kısa sorular sor; cevapları kaynak notlara kaydet. Sonra birlikte bir görev oluşturup tekrar okuyalım.

Kurulu üç skill:

| Skill | Ne zaman kullanılır? |
| --- | --- |
| **beyin** | Not bulmak, bilgi kaydetmek, görev değiştirmek, iş sonucu ve ders çıkarmak |
| **beyin-doktor** | Bir not bulunamıyorsa, bağlantı veya kayıt sorunu varsa |
| **beyin-guncelle** | Kurulu sistemi kontrol etmek, güncellemek veya geri almak |

Bunlar `.agents/skills` altında bulunur; istemciler aynı kaynakları kullanır. Eklemek istediğin kişisel skill'leri ayrıca içe alabilirsin. Aynı adlı farklı içerik sessizce ezilmez.

## Günlük kullanım

Notu yaz, ajana ne istediğini söyle. Kaynaklar oturum açılışı ve konuşmanın uygun noktalarında yeniden indekslenir. İstemciler kapalıyken sürekli tarayan bir servis yoktur. Önemli iş sonuçları kısa, kaynak bağlantılı kayıtlarla tutulur; tüm sohbetin kendiliğinden doğru bilgiye dönüştüğü iddia edilmez.

Bir şey ters giderse ajana **“beyin-doktor ile kontrol et”** de. Terminalden, vault klasöründe:

```sh
python3 beyin.py doctor
```

Windows'ta aynı komutun başında `py -3` kullan. Kurulumda özel runtime yolu seçtiysen kurulu `beyin.py` bunu zaten bilir.

## Tüketim ve kontrol sıklığı

Ajanına **“ekonomik moda geç”**, **“otomatik kontrolleri kapat”** veya **“kontrol aralığını 30 dakika yap”** diyebilirsin. Üç istemci aynı vault tercihini kullanır; güncellemeler tercihini korur.

| Mod | Yerel kontrol | Oturuma eklenen bağlam |
| --- | --- | --- |
| Normal (varsayılan) | Her ilgili istemci olayında | Oturum başı ve mesajlarda, en çok 5000 karakter |
| Ekonomik | Yeni oturumda; sonrasında en az 15 dakika aralıklı | Yalnız oturum başında, en çok 2000 karakter |
| Manuel | Otomatik kapalı | Otomatik kapalı |

Süre dolunca kendi başına çalışan bir zamanlayıcı kurulmaz; bir sonraki istemci olayı kontrolü başlatır. İstemciler kapalıyken işlem yapılmaz. Yerel Python kontrolleri **model çağırmaz**; otomatik Luna/Sonnet maliyeti yoktur. Ajana yaptırdığın işler ve eklenen bağlam normal istemci tüketimine girer. Ekonomik veya manuel modda gerektiğinde kaynaklar açık `context`/`sync` komutuyla tazelenir.

İsteğe bağlı Jev danışmanı bundan ayrıdır: varsayılan kapalıdır, yalnız kendi TypeSafe API anahtarı olanlar içindir ve kurucu onu ne sorar ne kurar. Durumu `python3 beyin.py jev status` gösterir; `jev shadow`, `jev on` ve `jev off` ile değiştirilir. [Ayrıntılar ve sınırlar](docs/v3/JEV.md).

Tercihler: `python3 beyin.py preferences`. Ekonomik: `preferences --profile economical`. Manuel: `preferences --profile manual`. Aralık: `preferences --interval-minutes 30`. Opt-in sır süzgeci: `preferences --secret-filter on`. Windows'ta `py -3` kullan. [Ayrıntılar](docs/v3/PREFERENCES.md).

## Güncelleme

Ajanına **“beynimi güncelle”** diyebilir veya vault içindeki kısayolu açabilirsin:

- macOS: `Beyni Güncelle.command`
- Windows: `Beyni Guncelle.cmd`
- Linux: `Beyni Güncelle.desktop` veya `Beyni Güncelle.sh`

Kısayol aynı updater'ı çalıştırır. Terminalde önce kontrol etmek istersen:

```sh
python3 beyin.py update --check
python3 beyin.py update
```

Yeni sürüm kontrolü varsayılan olarak açıktır: oturum başında ayrı bir süreç günde en fazla bir kez GitHub sürüm bilgisini kontrol eder. Not, prompt veya hesap bilgisi göndermez; model çağırmaz. İlk sonuç sonraki oturumda veya `doctor` çıktısında görünür. Aynı sürüm için bildirim bir kez gösterilir. Otomatik kurulum yapılmaz.

- Hafif kontrol: `python3 beyin.py update --check --metadata-only`
- Bildirimi kapat: `python3 beyin.py preferences --update-notifications off`
- Aç: `python3 beyin.py preferences --update-notifications on`
- Bir sürümü sustur: `python3 beyin.py update --dismiss 3.1.0`

Windows'ta `python3` yerine `py -3` kullan. V3.0.2 kurulumunda yeni seçenekler ilk `update` işleminden sonra gelir.

Varsayılan kaynak yalnız resmi GitHub **stable release** paketidir; geliştirme dalından kendiliğinden kod çekmez. Paket yayınlanmamışsa veya erişilemiyorsa hata bildirir, güncellenmiş gibi davranmaz. İndirilmiş ZIP ile çevrimdışı güncelleme ve geri alma için [güncelleme rehberi](docs/v3/UPDATE.md).

## V2'den geliyorsan

Aynı kurucuyu mevcut vault üzerinde çalıştır. Notlar, Companion dosyaları, eski `daily/` ve `knowledge/` içerikleri korunur. Tanınan eski writer'lar geri alınabilir biçimde devreden çıkarılır; özelleştirilmiş sistem dosyası veya çalışan eski worker varsa işlem durur ve açıklama verir.

V2'nin arka planda model çağıran günlük özetleyici/derleyici akışı V3'te çalışmaz. Bunun yerine aktif ajan bilinçli olarak iş sonucu ve bilgi notu yazar. Yeni sonuç bağlantıları `daily/v3/` ve `knowledge/v3/outcomes.md` altında oluşturulur. Eski günlükler yeniden özetlenmez. [Geçiş ve sınırları](docs/v3/MIGRATION.md) · [Tarihsel V2 rehberi](docs/V2-README.md).

## Ne korunur, ne ölçülür?

Kullanıcı notları updater'ın değiştireceği sistem dosyaları değildir. Yönetilen dosyada farklı bir değişiklik görülürse conflict bildirilir; ilgisiz desteklenen ayar değişiklikleri birleştirilir. Yedek ve journal vault dışında yereldir. Bir kesinti sonrası `recover` veya `rollback` kullanılabilir.

Arama yerel kelime eşleştirmesi kullanır; genel doğal dil anlama veya her soruda doğru hatırlama sözü vermez. Motor kendisi model çağırmaz; ajana yaptırdığın işler istemcinin normal kullanımına girer. Otomatik doğrulamalar ve gerçek istemci kontrolleri [ayrı raporlanır](docs/v3/README.md).

## Geliştiriciler

[Kaynak formatı](docs/v3/MARKDOWN.md) · [Runtime](docs/v3/RUNTIME.md) · [Semantik test sözleşmesi](docs/v3/SEMANTIC-TEST-CONTRACT.md) · [Sürüm paketi ve updater](docs/v3/UPDATE.md).

Açık kaynak, [MIT lisansı](LICENSE). Avenox tarafından günlük ikinci beyin iş akışlarından geliştirildi. V2 bilgi derleme fikri için [Karpathy'nin bilgi tabanı desenine](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) teşekkürler.
