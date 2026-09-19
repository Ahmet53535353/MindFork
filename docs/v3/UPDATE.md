# Kurulum, güncelleme ve geri alma

Vault içindeki `beyin.py` tek giriş noktasıdır. Komutları vault klasöründe çalıştır. Aşağıdaki örneklerde macOS/Linux için `python3` kullanılır; Windows'ta bunun yerine `py -3` yazılır. Python 3.11+ gerekir.

## Git kullanmadan ilk kurulum

[V3.0.2 release sayfasından](https://github.com/avenoxai/avenoxbeyin/releases/tag/v3.0.2) `beyin-v3-3.0.2.zip` indirip aç. Paket ve minimum gereksinimler sürüm sayfasında belirtilir. GitHub'ın otomatik kaynak arşivi ile ürün paketi farklıdır.

Bir vault klasörü seç veya oluştur. Açılan paketin içinde:

```sh
python3 scripts/install_v3.py --vault "/tam/yol/Beynim"
```

Windows örneği:

```powershell
py -3 scripts/install_v3.py --vault "C:\Notlar\Beynim"
```

Runtime varsayılan olarak işletim sisteminin yerel uygulama verisi alanına, vault dışında kurulur. İstersen kurulumda `--state "/ayri/yerel/dizin"` verebilirsin; yalnız bu uygulama için ayrılmış bir dizin seç. Kurulu giriş ve başlatıcılar bu seçimi hatırlar. Yeni hesap, Git, pip veya servis kurulmaz.

İlk bağlantı için AI istemcisinde vault'u açıp yeni oturum başlat. Hook tanımları değiştiğinde istemcinin gerekli güven incelemesini tamamla; updater güven kaydı üretmez.

## Kontrol ve güncelleme

```sh
python3 beyin.py doctor
python3 beyin.py update --check
python3 beyin.py update
```

`doctor` yerel kayıtları, bekleyen işleri ve sorunları gösterir. Bir metadata raporu gerçek istemci teslimi veya her notun doğru yorumlandığı kanıtı değildir.

`update --check` resmi stable release'i inceler ve paketi geçici alanda doğrular. Vault ve mevcut runtime dosyalarını değiştirmez. Paket verilmezse ağ erişimi gerekir. `update` aynı doğrulamadan sonra yeni sürümü uygular. Aynı sürüme ikinci güncelleme no-op'tur; sayısal sürüm sırası kullanılır. Eski bir paketi yükleyerek downgrade yapılmaz; geri dönüş için `rollback` kullanılır.

Varsayılan indirme kaynağı `avenoxai/avenoxbeyin` deposunun resmi GitHub stable release'idir. Preview, hareket eden geliştirme dalı veya üçüncü taraf paket kaynağı otomatik seçilmez. Stable release ya da beklenen ZIP yoksa bunu hata olarak bildirir; yayın varmış gibi sonuç vermez.

Yerel, önceden indirilmiş ZIP ile ağ gerekmez:

```sh
python3 beyin.py update --check --package "/indirilen/beyin-v3-3.0.2.zip"
python3 beyin.py update --package "/indirilen/beyin-v3-3.0.2.zip"
```

Yerel paketi yalnız güvendiğin kaynaktan al: checksum bütünlüğü kontrol eder; bağımsız bir imza veya kaynak güveninin yerine geçmez.

## Tıklanabilir başlatıcılar

Kurucu vault'a yalnız ilgili platformun başlatıcısını koyar:

| Platform | Başlatıcı |
| --- | --- |
| macOS | `Beyni Güncelle.command` |
| Windows | `Beyni Guncelle.cmd` |
| Linux | `Beyni Güncelle.desktop` ve `Beyni Güncelle.sh` |

Hepsi kurulu `beyin.py update` komutunu çağırır, ayrı güncelleme mantığı içermez. İşletim sistemi dosyanın açılması/çalıştırılması için izin isteyebilir. Özel Python/runtime yolu kurulumda kaydedilir; Python'u sonradan taşıdıysan kurulumu yeniden değerlendirmek gerekir.

## Kesinti veya sorun

```sh
python3 beyin.py recover
python3 beyin.py rollback
```

`recover`, yarım kalan işlemin journal'ını okuyup planlanan işlemi tamamlar. Bir hata mesajı işlemin iptal edildiği anlamına gelmez; bazı sistem dosyaları yazılmış, başarılı sürüm damgası henüz yazılmamış olabilir.

`rollback`, son sistem işleminin yedeğini geri getirir. İlk V2 geçişinde önceki sürüm ve tanınan eski runner'lar da geri yüklenir. Temiz V3 kurulumunu geri almak `uninstalled` olarak raporlanır; olmayan bir eski sürüm uydurulmaz. Sonradan eklediğin kullanıcı notları silinmez. Bu komut bütün vault geçmişini geri alan bir işlem değildir.

Yönetilen dosyada araya giren kullanıcı değişikliği varsa işlem bunu ezmek yerine conflict ile durur. Desteklenen JSON ayarlarında ilgisiz değişiklikler korunur; çakışan yönetilen bölüm için inceleme gerekir. Kilitli/aktif bir writer varsa tamamlanmasını bekleyip tekrar dene. Kaybolmuş bir işin kilit/sentinel dosyasını gelişigüzel silme.

Yalnız satır sonu farkı değişiklik sayılmaz: `core.autocrlf` ya da bir editör yönetilen dosyayı CRLF'e çevirmişse güncelleme, kaldırma ve rollback durmaz, dosya yeniden yazılırken stok LF biçimine döner. Conflict mesajı sebebi söyler: `content differs` gerçek bir düzenleme, `deleted` silinmiş dosya demektir.

## Neler değişir?

Paket yalnız yönetilen motor dosyaları, kurulu giriş/başlatıcılar, üç çekirdek skill ve istemci bağlantılarını günceller. Aynı adlı özel skill veya değiştirilmiş yönetilen script sessizce ezilmez. İlgisiz kullanıcı ayarları desteklenen birleştirme kurallarıyla korunur. Markdown notlar, Companion metinleri ve eski günlük/bilgi kaynakları paket içeriğiyle değiştirilmez.

V2 geçişinde hash ile tanınan stok writer'lar geri alınabilir, etkisiz girişlerle değiştirilir. Böylece önceden açılmış istemcide kalan eski komut da model derleyicisini yeniden başlatmaz. Özelleştirilmiş runner'lar ve proje dışındaki zamanlayıcılar ayrıca değerlendirilir. [Geçiş rehberi](MIGRATION.md).

## Uygulanan kontroller

Arşiv izin listesi, dosya SHA256, sürüm ve runtime şeması doğrulanır. Paket Python dosyaları derlenir; yeni kod ayrı sentetik vault'ta init, sync, kaynak arama ve receipt testinden geçer. Gerçek vault notları bu test için kullanılmaz. Uygulamada yerel kilit, önceki/yeni dosya içerikleri ve modlarıyla kalıcı journal, yönetilen dosya hash kontrolleri ve sürümden önce runtime veritabanı kontrolü vardır. Sürüm damgası en son yazılır.

Bu kontroller dağıtık cloud kilidi veya bütün harici uygulamalar için atomik transaction değildir. Başka bir editörün görülen değişiklikleri korunur; gerçek istemci davranışı ayrı doğrulanır. [Platform raporu](PLATFORM-TESTS.md).

## Geliştiriciler için paket üretimi

Repo kökünde:

```sh
python3 scripts/build_v3_release.py --output "/tmp/beyin-v3-3.0.2.zip" --version 3.0.2
```

Bu komut yalnız yerel ZIP oluşturur, GitHub'a yayınlamaz. Paket `manifest.json`, izin verilen installer/giriş dosyaları, runtime modülleri ve üç skill'i içerir. Manifest sürüm, schema/runtime schema, minimum Python, dosya hashleri ve tanınan legacy hashlerini taşır. Release yayınlama ve final platform CI ayrı işlemlerdir.
