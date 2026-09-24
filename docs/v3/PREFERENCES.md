# Otomatik kontrol ve bağlam tercihleri

Kullanıcı ayarı `.beyin-preferences.json` içinde; yönetilen release dosyası değildir. Installer, updater ve rollback bu dosyayı değiştirmez. Dosya yoksa mevcut normal davranış korunur. Ortak Python uygulaması Windows, macOS ve Linux'ta aynı ayarları okur; yeni servis veya model bağımlılığı yoktur.

## Stop'ta receipt hatırlatması

Claude veya Codex oturumu dosya düzenleme araçlarından birini kullandıysa ve transcript'te receipt komutu yoksa, Stop hook'u bir kez `python3 beyin.py receipt --file RECEIPT_JSON --harness claude` (veya mevcut istemci) komutunu hatırlatır; transcript yoksa ya da bozuksa akış durdurulmaz. Kullanıcı mesajında `[kaydetme]` yazarak bu oturumdaki hatırlatmayı atlayabilir veya `BEYIN_V3_NO_RECEIPT_REMINDER=1` ile özelliği kapatabilir.

`python3 beyin.py preferences --profile economical` ile ekonomik, `--profile normal` ile normal, `--profile manual` ile manuel kullanım. Argüman verilmezse ayarlar okunur. Ajan bunları beyin skill'i üzerinden uygular. `--human` okunabilir çıktı sağlar.

Alanlar: `auto_sync` boolean; `interval_minutes` 0–1440 (0 her olay); `context_mode` turn/session/off; `context_chars` 1000–12000. Karakter sınırı ek hook bağlamının tamamına uygulanır; token kotası değildir. Sayısal ve bilinmeyen alanlar doğrulanır, hatalı dosya sessizce ezilmez.

Ekonomik profil: auto_sync=true, interval_minutes=15, context_mode=session, context_chars=2000. Manuel: auto_sync=false ve context_mode=off. Mevcut ayarların yalnız bir alanını değiştirmek için örneğin `preferences --interval-minutes 30`; profil seçmek otomatik kontrol ve bağlam alanlarını o profile sıfırlar, bağımsız sır süzgeci tercihini korur. Aralık değiştirmek kapalı kontrolü açmaz.

## Opt-in sır süzgeci

`python3 beyin.py preferences --secret-filter on` komutu receipt özeti, note-create gövdesi ve task-create gövdesinde yaygın erişim anahtarı biçimlerini yazmadan önce `[REDACTED]` ile değiştirir. Varsayılan kapalıdır; profil değişikliği bu bağımsız tercihi değiştirmez. Kapatmak için `--secret-filter off` kullan.

Ek sabit sır değerleri vault dışındaki runtime klasöründe `secret-patterns.txt` dosyasına, satır başına bir değer olarak yazılabilir. Dosya regex çalıştırmaz; yorum satırları `#` ile başlar. Eşleşen metinler veya değerler sağlık kaydına yazılmaz, yalnız toplam eşleşme sayısı `doctor` sonucunda gösterilir. Bu önlem kazara kalıcı yazımı azaltır; tam bir DLP veya önceden yazılmış notları temizleme aracı değildir.

Süre en son otomatik başlatmaya göre yerel SQLite kaydıyla, istemciler arasında atomik olarak sınırlandırılır. Bir sonraki olay gelmedikçe kontrol çalışmaz. Yeni oturumda daima taze kontrol; kaydedilmiş worker hatasında yeniden deneme. Bu düşük seviyeli kontrol model çağırmaz. Otomatik bağlam kapalı olsa bile açık not/görev/receipt ve context komutları çalışır. Kapatmadan önce başlatılmış bir işlem tamamlanabilir; önceden bekleyen metadata saklanır. Açık `--drain-queue` bakım komutu bu kuyruğu işler.

Aralığa takılmış bir kontrolde turn bağlamı istenirse eski kayıtları güncel diye sunmak yerine kısa tazeleme uyarısı verilir. Ekonomik modda sonraki mesajlarda tekrar bağlam eklenmez; beyin skill'i bilgi gerektiğinde kaynakları doğrudan tazeler.

Özel V2 cron/LaunchAgent/Task Scheduler işleri veya kullanıcının ayrı kurduğu 15 dakikalık ücretli ajan otomasyonları bu tercihlerle kapatılmaz. Önce ilgili işi tespit edip ayrı yönetmek gerekir. V3 kendiliğinden Luna/Sonnet çalıştırmaz.

Bu değişiklik yerel adaydır; yayımlanmış v3.0.0 paketine otomatik olarak eklenmez. Yeni paket yayımlanmadan kullanıcılara mevcut sürüm özelliği diye duyurulmamalıdır.
