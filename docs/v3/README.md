# İkinci Beyin V3

V3, mevcut vault içine isteğe bağlı kurulan ortak yerel motordur. Markdown kaynak, SQLite yeniden oluşturulabilir yerel indeks, Codex/Claude Code/Antigravity ise aynı motora bağlanan istemcilerdir. Mem0, API anahtarı, sunucu ve ek Python paketi gerekmez. Python 3.11+ kullanılır.

[Kısa kurulum](../../SETUP-V3.md) · [Komut rehberi](QUICKSTART.md) · [Kaynak şeması](MARKDOWN.md) · [Runtime](RUNTIME.md)

## Uygulananlar

- Markdown ekleme, düzenleme, silme ve yeniden adlandırma senkronizasyonu. Görev güncellemesi revision kontrolüyle kaynak dosyasına yazılır; kullanıcı gövdesi korunur.
- Kısa lifecycle hook, kalıcı metadata kuyruğu ve gerektiğinde başlayan yerel worker. Sistem servisi kurulmaz; istemciler kapalıyken sürekli tarama yapılmaz.
- Kaynak bağlantılı receipt, tekrar denemede aynı sonuç, işlem geçmişi ve kesinti sonrası kurtarma. Ham özel sohbetlerden otomatik doğrulanmış bilgi üretilmez.
- Ortak skill deposu `.agents/skills`, Claude erişimi `.claude/skills`. POSIX symlink, Windows hash takibiyle kopya; eşzamanlı değişiklikler ezilmez. Seçilen kullanıcı skill'i içe alınabilir.
- Yedekli, tekrar çalıştırılabilir kurulum ve değişiklik korumalı geri alma. Kurulu vault, bu repo klasörü olmadan da çalışır.
- macOS/Linux/Windows yolları ve Windows'un yerleşik PowerShell başlatıcısı. Gerçek platform kanıtları aşağıdaki raporda ayrı gösterilir.

## Doğrulama

[Platform testleri](PLATFORM-TESTS.md) ve [gerçek istemci oturumları](LIVE-CLIENTS.md) güncel kanıtlardır. Daha eski araştırma ve temel koşuları aşağıda tarihsel kayıt olarak korunur.

[Önceden sabitlenen semantik sözleşme](SEMANTIC-TEST-CONTRACT.md) üzerinde development **10/10**, holdout **6/6**. Gerekli kayıt recall ve abstention doğruluğu %100; diagnostic precision development %95, holdout %100; yasak kayıt/sentetik gizlilik canary ihlali 0. [Başlangıç karşılaştırması](BASELINE.md).

Bu küçük küme kaynak bulma, durum, revizyon ve yapılandırılmış bilgiyi ölçer. Motor kelime tabanlı yerel arama kullanır; embedding veya genel doğal dil anlama başarısı iddia edilmez. Holdout ilk koşuda da geçmişti. Gerçek istemci testleri sentetik örneklerle sınırlıdır.

## Yayın öncesi kalanlar

- Native Windows CI çalıştırması; matris yazılmış olması başarı kanıtı değildir.
- Codex Desktop için ayrıca soğuk oturum/arayüz doğrulaması. CLI kanıtı Desktop kanıtının yerine geçmez.
- Eski V2 indeksinin otomatik migration'ı ve eski compiler akışının tam dönüşümü bu opt-in sürümün kapsamı dışındadır. Yeni indeks Markdown kaynaklardan kurulur; eski notlar taşınmaz.

Mem0 için opt-in factory arayüzü bulunur; hazır SDK/servis adaptörü bu sürümde yoktur. V3 kurulumu eski V2 kurulumundan ayrıdır. V3 değişiklikleri henüz GitHub’a gönderilmedi veya PR ile birleştirilmedi.

## Araştırma kaydı

İncelenen public taban `2e074cc` (15 Eylül 2026). Kişisel vault içeriği public ürüne taşınmadı.

[Public mimari](public-architecture.md) · [Yerel mimari](local-runtime-architecture.md) · [Eşitlik/migration](parity-and-migration.md) · [Açık sorunlar](issue-validation.md) · [Serai desenleri](SERAI-PATTERNS.md)
