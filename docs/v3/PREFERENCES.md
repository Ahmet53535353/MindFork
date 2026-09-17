# Otomatik kontrol ve bağlam tercihleri

Kullanıcı ayarı `.beyin-preferences.json` içinde; yönetilen release dosyası değildir. Installer, updater ve rollback bu dosyayı değiştirmez. Dosya yoksa mevcut normal davranış korunur. Ortak Python uygulaması Windows, macOS ve Linux'ta aynı ayarları okur; yeni servis veya model bağımlılığı yoktur.

`python3 beyin.py preferences --profile economical` ile ekonomik, `--profile normal` ile normal, `--profile manual` ile manuel kullanım. Argüman verilmezse ayarlar okunur. Ajan bunları beyin skill'i üzerinden uygular. `--human` okunabilir çıktı sağlar.

Alanlar: `auto_sync` boolean; `interval_minutes` 0–1440 (0 her olay); `context_mode` turn/session/off; `context_chars` 1000–12000. Karakter sınırı ek hook bağlamının tamamına uygulanır; token kotası değildir. Sayısal ve bilinmeyen alanlar doğrulanır, hatalı dosya sessizce ezilmez.

Ekonomik profil: auto_sync=true, interval_minutes=15, context_mode=session, context_chars=2000. Manuel: auto_sync=false ve context_mode=off. Mevcut ayarların yalnız bir alanını değiştirmek için örneğin `preferences --interval-minutes 30`; profil seçmek tüm alanları o profile sıfırlar. Aralık değiştirmek kapalı kontrolü açmaz.

Süre en son otomatik başlatmaya göre yerel SQLite kaydıyla, istemciler arasında atomik olarak sınırlandırılır. Bir sonraki olay gelmedikçe kontrol çalışmaz. Yeni oturumda daima taze kontrol; kaydedilmiş worker hatasında yeniden deneme. Bu düşük seviyeli kontrol model çağırmaz. Otomatik bağlam kapalı olsa bile açık not/görev/receipt ve context komutları çalışır. Kapatmadan önce başlatılmış bir işlem tamamlanabilir; önceden bekleyen metadata saklanır. Açık `--drain-queue` bakım komutu bu kuyruğu işler.

Aralığa takılmış bir kontrolde turn bağlamı istenirse eski kayıtları güncel diye sunmak yerine kısa tazeleme uyarısı verilir. Ekonomik modda sonraki mesajlarda tekrar bağlam eklenmez; beyin skill'i bilgi gerektiğinde kaynakları doğrudan tazeler.

Özel V2 cron/LaunchAgent/Task Scheduler işleri veya kullanıcının ayrı kurduğu 15 dakikalık ücretli ajan otomasyonları bu tercihlerle kapatılmaz. Önce ilgili işi tespit edip ayrı yönetmek gerekir. V3 kendiliğinden Luna/Sonnet çalıştırmaz.

Bu değişiklik yerel adaydır; yayımlanmış v3.0.0 paketine otomatik olarak eklenmez. Yeni paket yayımlanmadan kullanıcılara mevcut sürüm özelliği diye duyurulmamalıdır.
