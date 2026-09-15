# 🧠 avenoxbeyin V3

Claude Code, Codex veya Google Antigravity ile kullanabileceğin yerel ikinci beyin. Notların Markdown dosyalarında kalır; bir istemcide kaydettiğin kaynak ve iş sonucu diğerinde de bulunabilir. Obsidian ile açabilir, normal bir metin editörüyle düzenleyebilirsin.

Python **3.11 veya üzeri** yeterli. Git, pip, Mem0 hesabı, API anahtarı veya sürekli açık sunucu gerekmez. Kullandığın AI istemcisinin kendi kurulumu ve hesabı ayrı olarak gerekir.

> **Yayın durumu:** V3 kullanıcı paketi ve updater uygulandı. Bu belge hazırlanırken `v3.0.0` stable yayını henüz doğrulanmış değildi. Aşağıdaki sürüm sayfasında ZIP dosyası görünmeden yayını hazır kabul etme. Güncel doğrulama [platform raporunda](docs/v3/PLATFORM-TESTS.md).

## İlk kurulum

1. [V3.0.0 sürüm sayfasını](https://github.com/avenoxai/avenoxbeyin/releases/tag/v3.0.0) aç. Yayınlandığında **[beyin-v3-3.0.0.zip](https://github.com/avenoxai/avenoxbeyin/releases/download/v3.0.0/beyin-v3-3.0.0.zip)** dosyasını indir ve aç. GitHub'ın otomatik “Source code” arşivi yerine bu paketi seç.
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

Vault klasörünü kullandığın AI istemcisinde açıp **yeni bir oturum başlat**. Codex'te `/hooks` ekranında yeni hook tanımlarını inceleyip güven; diğer istemcilerde workspace güvenini tamamla. İstemci güvenini kurucu senin adına uydurmaz. Agent ile kurulum yapmak istersen [SETUP-V3.md](SETUP-V3.md) rehberini takip etmesini iste.

## İlk konuşma

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
