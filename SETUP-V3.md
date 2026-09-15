# V3 kurulumu: ajan için kısa rehber

Kullanıcı bu dosyayı takip etmeni istediğinde mevcut Codex, Claude Code veya Antigravity oturumunda çalış. Yeni hesap, API anahtarı, Mem0, sunucu veya paket yöneticisi kurma. Ortak motor yalnız Python standart kütüphanesini kullanır.

1. Kullanıcının seçtiği vault yolunu kullan. Belirsizse yalnız hangi klasörü kullanacağını sor. Yeni vault isteniyorsa klasörü oluştur; mevcut notları taşıma veya silme.
2. İşletim sistemini ve çalışan Python'u doğrula: macOS/Linux `python3`, Windows `py -3` veya çalışan `python`. Python 3.11+ önerilir. Yorumlayıcı yoksa eksik gereksinimi açıkça söyle; kuruluymuş gibi devam etme.
3. Repo kökünden çalıştır: `python3 scripts/install_v3.py --vault "VAULT_YOLU"`. Windows'ta aynı komutun başında `py -3` kullan. Installer yerel yedek alır, ortak motoru vault'a kopyalar ve üç istemci için hook bağlantısı kurar. Sistem servisi yüklemez.
4. Kurulan CLI ile kontrol et: `python3 "VAULT_YOLU/.claude/scripts/beyin_v3_cli.py" --vault "VAULT_YOLU" doctor`. Hataları ve skill çakışmalarını açıkça bildir. Çalışan servis veya gerçek istemci testi olmadan 'her şey sağlıklı' deme.
5. Codex kullanılıyorsa vault klasöründe yeni oturum açıp `/hooks` üzerinden yeni hook tanımlarını incele ve güven. Trust hashlerini elle yazma; kurulumda trust bypass kullanma. Claude için yeni oturum aç. Antigravity içinde vault klasörünü workspace olarak açıp klasöre güven; headless çalıştırırken `--add-dir "VAULT_YOLU"` kullan. Modelden, sentetik bir nottaki bilgiyi yalnız hook context üzerinden döndürmesini isteyerek bağlantıyı doğrula. Gerçek özel veriyi test çıktısına alma.
6. Skill'lerin ortak erişim noktası `.agents/skills/`; Claude karşılığı `.claude/skills/`. Mevcut skill'ler korunur. Ek skill için yalnız kullanıcının seçtiği dizini `skill-import --source "SKILL_DIZINI"` ile al. İki tarafta farklı değişiklik varsa kullanıcı metnini koruyup conflict bildir.
7. İş bitince kullanıcıya yalnız vault yolu, çalışan istemci bağlantıları ve varsa tek sonraki adımı söyle. JSON/debug dökümü, global ayarlar veya kişisel bilgileri sohbet çıktısına taşıma.

## Kullanıcıya açıklanacak sınır

Not kaydedildiğinde dosya kalıcıdır. İndeks oturum başı, mesaj gönderimi ve tur sonu gibi hook noktalarında tazelenir; istemciler kapalıyken sürekli arka plan hizmeti çalışmaz. Gerektiğinde kurulan CLI `sync` komutu anında tazeler. Çalışma sonuçları yapılandırılmış receipt ile kaydedilir; bütün özel sohbet geçmişi kendiliğinden içeri alınmaz.

Basit scalar YAML ve JSON frontmatter desteklenir. Karmaşık YAML görünür uyarı üretir; sessizce yanlış metadata çıkarılmaz. Önce kaynak not okunarak ihtiyaç duyulan alanlar anlaşılır. Kaynak task güncellemesi `task-update` ile expected revision kullanır; conflict durumunda güncel kaydı oku.

Geri alma: kurulum reposundan aynı vault/state ile `scripts/install_v3.py --uninstall`. Değiştirilmiş kurulum dosyası varsa geri alma durur ve kullanıcının yeni değişikliğini korur. Bu işlem kullanıcı notlarını silmez.

Platform kanıtı ve kalan doğrulamalar: [docs/v3/PLATFORM-TESTS.md](docs/v3/PLATFORM-TESTS.md).
