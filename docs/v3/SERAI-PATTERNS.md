# Serai tasarım incelemesinden taşınabilir desenler

İlk bağımsız kaynak incelemesi gpt-5.6-sol ile yapıldı. Yalnız teknik tasarım özeti aktarılır; kaynak kod, özel veri ve ortam yapılandırması kopyalanmadı. Serai servisi veya Mem0 bu projeye bağımlılık olarak eklenmez.

## V3 temelinde uygulanacak küçük parça

Bir nesnenin yeni durumu ile o değişimin olay kaydını aynı SQLite transaction içinde yazmak. Başarısız expected-revision kontrolü hiçbir olay üretmez; aynı ingest yeniden gönderilirse geçmiş çoğalmaz. Sıralı snapshot geçmişi, daha sonra denetlenebilir restore ve indeks yeniden oluşturma için temel sağlar. Bu aşama tüm çıktı dosyaları için crash-recovery worker anlamına gelmez.

## Korunan diğer ilkeler

- Idempotency anahtarının farklı içerikle tekrar kullanılması hata olmalı.
- Arama çıktısının kaynak yolu ve kaynak sürümü/hash bilgisi korunmalı; değişen kaynağın eski indeksi güncelmiş gibi sunulmamalı.
- Revision conflict, otomatik aynı yazıyı yeniden deneme sebebi değildir; yeni durum okunur.
- Dış etki varsa önce niyet, sonra sonuç kaydı gerekir. Sonucu bilinmeyen dış etki otomatik tekrarlanmamalı. V3 temelinde dış etki çalıştırıcısı yok.
- Çok kullanıcılı politika, bulut backend, onay rezervasyonu ve dağıtık kontrol katmanları küçük yerel ürüne taşınmaz.

## İnceleme kanıt sınırı

İlk ajan kaynak kodu okudu, gerçek Serai testi çalıştırmadı. Hub bootstrap ve kapanış bu ortamda başarılı olmadığından Serai tarafından doğrulanmış oturum receipt'i iddiası yok. Yerel V3 doğrulaması ayrıca sentetik testlerle yapılır.

## İkinci Sol incelemesi: kaynak ve bağlam doğruluğu

İkinci gpt-5.6-sol ajanı kaynak kimliği/sınırı, içerik sürümü, bağlam bütçesi, cevap vermekten kaçınma ve seçim telemetrisi desenlerini ayrı inceledi. Kaynak hash değişince eski kaydın dışlanması, kaynak/vault ayrımı, deterministik bütçe ve aynı bağlamı üreten iki harness arayüzü bu temel için uygun parçalardır.

İnceleme ayrıca kopyalanmaması gereken iki riski işaretledi: belirsiz alias'ın ilk kaydı seçmesi ve çıktı bütçesi değiştiği halde cache anahtarının değişmemesi. V3 temelinde alias çözümleyici veya retrieval cache yok; eklendiklerinde bu durumlar ayrı kabul testleri olmalı. Büyük kaydın küçük ve uygun sonraki kayıtları engellememesi de korunmalı.

İki Sol süreci de exit 0 ile rapor üretti. Bulgular statik kaynak incelemesidir; gerçek Serai testleri veya hub oturum doğrulaması değildir. İkinci ajan da bootstrap/kapanış kapsamı oluşturamadığını bildirdi. Özel kaynak kodu kopyalanmadı ve Serai'de değişiklik yapılmadı.
