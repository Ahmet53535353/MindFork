# Otomatik kontrol ve bağlam tercihleri

Kullanıcı ayarı `.beyin-preferences.json` içinde; yönetilen release dosyası değildir. Installer, updater ve rollback bu dosyayı değiştirmez. Dosya yoksa mevcut normal davranış korunur. Ortak Python uygulaması Windows, macOS ve Linux'ta aynı ayarları okur; yeni servis veya model bağımlılığı yoktur.

`python3 beyin.py preferences --profile economical` ile ekonomik, `--profile normal` ile normal, `--profile manual` ile manuel kullanım. Argüman verilmezse ayarlar okunur. Ajan bunları beyin skill'i üzerinden uygular. `--human` okunabilir çıktı sağlar.

Alanlar: `auto_sync` boolean; `interval_minutes` 0–1440 (0 her olay); `context_mode` turn/session/off; `context_chars` 1000–12000. Karakter sınırı ek hook bağlamının tamamına uygulanır; token kotası değildir. Sayısal ve bilinmeyen alanlar doğrulanır, hatalı dosya sessizce ezilmez.

Ekonomik profil: auto_sync=true, interval_minutes=15, context_mode=session, context_chars=2000. Manuel: auto_sync=false ve context_mode=off. Mevcut ayarların yalnız bir alanını değiştirmek için örneğin `preferences --interval-minutes 30`; profil seçmek otomatik kontrol ve bağlam alanlarını o profile sıfırlar, bağımsız sır süzgeci tercihini korur. Aralık değiştirmek kapalı kontrolü açmaz.

## Hafıza dosyası sınırları

`Last-Session.md` varsayılan olarak 3.000, `Threads.md` 8.000 karakterle sınırlıdır.
`python3 beyin.py preferences --last-session-chars 4000 --threads-chars 12000` sınırları
1.000 ile 200.000 arasında değiştirir, `0` ilgili sınırı kapatır. Bu iki alan vault
tercih dosyasında değil, runtime klasöründeki `companion-limits.json` dosyasında tutulur:
eski sürümler bilinmeyen tercih alanını reddettiği için rollback güvenli kalır, ayar ise
makineye özeldir. Profil değişikliği sınırları sıfırlamaz. Hatalı değer veya bozuk sınır
dosyası hiçbir ayarı kaydettirmez. Sınır aşılınca oturum başındaki uyarı, `doctor` raporu
ve kayıpsız `companion-compact` komutu [companion incelemesinde](COMPANION-PARITY.md)
anlatılır.

## Opt-in sır süzgeci

`python3 beyin.py preferences --secret-filter on` komutu receipt özeti, note-create gövdesi ve task-create gövdesinde yaygın erişim anahtarı biçimlerini yazmadan önce `[REDACTED]` ile değiştirir. Varsayılan kapalıdır; profil değişikliği bu bağımsız tercihi değiştirmez. Kapatmak için `--secret-filter off` kullan.

Ek sabit sır değerleri vault dışındaki runtime klasöründe `secret-patterns.txt` dosyasına, satır başına bir değer olarak yazılabilir. Dosya regex çalıştırmaz; yorum satırları `#` ile başlar. Eşleşen metinler veya değerler sağlık kaydına yazılmaz, yalnız toplam eşleşme sayısı `doctor` sonucunda gösterilir. Bu önlem kazara kalıcı yazımı azaltır; tam bir DLP veya önceden yazılmış notları temizleme aracı değildir.

Süre en son otomatik başlatmaya göre yerel SQLite kaydıyla, istemciler arasında atomik olarak sınırlandırılır. Bir sonraki olay gelmedikçe kontrol çalışmaz. Yeni oturumda daima taze kontrol; kaydedilmiş worker hatasında yeniden deneme. Bu düşük seviyeli kontrol model çağırmaz. Otomatik bağlam kapalı olsa bile açık not/görev/receipt ve context komutları çalışır. Kapatmadan önce başlatılmış bir işlem tamamlanabilir; önceden bekleyen metadata saklanır. Açık `--drain-queue` bakım komutu bu kuyruğu işler.

Aralığa takılmış bir kontrolde turn bağlamı istenirse eski kayıtları güncel diye sunmak yerine kısa tazeleme uyarısı verilir. Ekonomik modda sonraki mesajlarda tekrar bağlam eklenmez; beyin skill'i bilgi gerektiğinde kaynakları doğrudan tazeler.

Özel V2 cron/LaunchAgent/Task Scheduler işleri veya kullanıcının ayrı kurduğu 15 dakikalık ücretli ajan otomasyonları bu tercihlerle kapatılmaz. Önce ilgili işi tespit edip ayrı yönetmek gerekir. V3 kendiliğinden Luna/Sonnet çalıştırmaz.

Bu değişiklik yerel adaydır; yayımlanmış v3.0.0 paketine otomatik olarak eklenmez. Yeni paket yayımlanmadan kullanıcılara mevcut sürüm özelliği diye duyurulmamalıdır.

## Stop'ta receipt hatırlatması

Kurulum, Claude ve Codex için PostToolUse hook'unu yalnız dosya düzenleyen araçlara bağlar (`Edit|Write|apply_patch`). Bu olay geldiğinde hook, vault dışındaki runtime klasörüne oturum kimliğinin hash'iyle adlandırılmış küçük bir düzenleme işareti yazar; transcript okunmaz. Kabuk komutuyla yapılan düzenlemeler bu olayı tetiklemez. Stop'ta runtime kaydında aynı istemci ve aynı `session` değeriyle, düzenlemelerden sonra yazılmış bir receipt yoksa hook oturum başına bir kez Stop'u engeller ve `python3 beyin.py receipt --file RECEIPT_JSON --harness claude` komutunu (Codex için `--harness codex`, Windows'ta `py -3`) `Receipt session=<değer>` bilgisiyle birlikte hatırlatır. Bu değer receipt JSON'undaki `session` alanına yazılmazsa receipt bu checkpoint'i kapatmaz. Receipt'ten sonra yapılan yeni düzenlemeler yeni bir pencere açar.

Stop olayı hatırlatmadan önce kuyruğa alınır. Runtime kaydı okunamazsa akış durdurulmaz. `stop_hook_active` taşıyan ikinci Stop, manuel profil (`auto_sync: false`) ve global köprü hatırlatma yapmaz; tek seferlik hakkı da harcamaz. Kullanıcı mesajında `[kaydetme]` yazarak bu oturumdaki hatırlatmayı kapatabilir; `BEYIN_V3_NO_RECEIPT_REMINDER=1` özelliği tamamen kapatır.
