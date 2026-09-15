# V3 kullanıcı paketi ve güncelleme planı

16 Eylül 2026. Aşağıdaki planın kullanıcı paketi, updater ve geçiş kodu uygulandı. İlk tasarım metni karşılaştırma için aşağıda korunur; “önerilen” veya “henüz yok” ifadeleri tasarım anını anlatır.

## Tamamlanma durumu

- Üç çekirdek skill dağıtılıyor: beyin, beyin-doktor, beyin-guncelle.
- Kurulu `beyin.py`: doctor, runtime komutları, update --check, update, recover, rollback. Özel runtime yolu korunuyor.
- ZIP builder: sürüm, schema/runtime schema, minimum Python, dosya SHA256 ve tanınan legacy hashleri. Git veya pip gerekmiyor.
- Updater: stable resmi release keşfi, yerel ZIP, sentetik runtime ön kontrolü, yönetilen dosya conflict kontrolü, yedek/journal/kilit, sürüm en son, tekrar çağrıda no-op.
- İlk V2 kurulumu dahil rollback; temiz kurulumun geri alınması `uninstalled` olarak raporlanır. Kullanıcı notları silinmez.
- V2 writer geçişi: aktif/özelleştirilmiş writer engelleri, tanınan stok runner'larda inert shim, kaynak/state koruma kontrolü ve geçiş kaydı.
- Yeni kaynak bağlantılı sonuçlar için deterministic daily/knowledge bağlantı görünümleri; otomatik model derleyicisinin yerine aktif ajan skill akışı.
- Yerel işletim sistemine uygun tıklanabilir güncelleme başlatıcıları aynı updater'a bağlı.

Son platform CI, paket yayını ve stable release varlığı bu uygulama listesiyle kanıtlanmış sayılmaz. Yayın, final CI ve release işlemi tamamlandıktan sonra doğrulanır. Bu belge güncellenirken `v3.0.0` yayını henüz doğrulanmamıştı. Kullanıcı akışı [README](../../README.md), komut sözleşmesi [UPDATE.md](UPDATE.md), güncel kanıt [PLATFORM-TESTS.md](PLATFORM-TESTS.md).

## İlk tasarım kaydı

## Doğrulanmış mevcut durum

V3 runtime ve üç istemci adaptörü hazır. Native CI Windows/macOS/Ubuntu × Python3.11/3.13:6/6, herjob62 V3 testi+semantik değerlendirme. Gerçek model oturumları macOS'ta ayrı doğrulandı. Kod deposundaki candidate standart V2 sürümünün yerini henüz almadı.

Temiz sentetik vault'a install_v3.py uygulandı: installed,5 Python modülü,0 SKILL.md, .beyin-version yok, sürümlü update komutu yok. Yerel kurulum manifesti yalnız files/commands alanlarını içeriyor. Mevcut template'te V2 beyin-doktor ve gecmis-import var; V3 installer bunları dağıtmıyor. V2 doktor Bash/eskihook yollarını kontrol ettiği için V3'e aynen kopyalanmamalı.

V2 upgrade.sh check/apply/finalize, yedek ve version stamp akışı sağlıyor; hedef2.3.0 ve Bash tabanlı. V3 installer yeni kodu yerleştirme, kullanıcı ayarı koruma ve geri alma altyapısını sağlıyor, ancak sürüm keşfi/indirme, V2 state geçişi, kesinti sonrası sürümlü upgrade devamı ve release yönetimi eksik.

V2 zaten varsayılan olarak yerel ve Mem0 gerektirmiyor. V2'nin flush→daily→compiler→knowledge hattı, V3 source/task/receipt indeksinin otomatik eşdeğeri değildir. Kullanıcıların mevcut günlük, companion ve derleme davranışlarını sessizce kaybetmeden geçiş tasarlanmalı.

## Minimal paket

Üç çekirdek skill: beyin (kaynak bulma, not/görev yazımı, revision, receipt ve gün sonu özeti), beyin-doktor (gerçek worker/istemci kanıtı, tazelik/çakışma, platforma uygun komutlar), beyin-guncelle (tek updater aracını çağırma ve sonucu açıklama). Bunlar sistem tarafından yönetilen .agents/skills girdileridir; Claude ve Antigravity aynı içerikleri görür. Seçilmiş kullanıcı skill'leri korunur. Aynı adlı kullanıcı skill'i varsa sessiz üstüne yazma olmaz; açık çakışma veya farklı sistem adı kullanılır. Kullanıcı özelleştirmeleri ayrıca tutulur.

AGENTS.md yeni kullanıcıya bu skill'leri yönlendirir. Kurulum sonunda üç kontrol: sentetik notu sonraki oturumda geri bul, görevi değiştirip tekrar oku, skill'i üç istemcide keşfet. Sonuçları tek kısa sağlık raporu gösterir. Geçmiş sohbet importu isteğe bağlı ve ayrı kalır.

## Tek güncelleme mekanizması

Önerilen giriş: vault içinde `python beyin.py update` (Windows: `py -3 beyin.py update`). `doctor`, `update --check` ve `rollback` aynı giriş altında olur. Bunlar henüz mevcut komutlar değildir. Kullanıcı ajana 'beynimi güncelle' dediğinde aynı aracı çağırır; ajan güncellemeyi serbest dosya kopyalama komutlarıyla yeniden tasarlamaz.

Release paketi standart kütüphane ile resmi GitHub HTTPS kaynağından alınır; Git/pip/yeni hesap zorunlu olmaz. Sabit release sürümü, dosya SHA256 listesi, minimum runtime/schema sürümü ve migration kimlikleri içerir. Checksum paket bütünlüğünü denetler; kaynak kimliği doğrulanmış resmi dağıtım adresine dayanır. Stable varsayılan; preview açık tercihtir. Hareket eden geliştirme dalından kendiliğinden güncellenmez.

Akış: sürümü algıla→planı göster→yerel yedek/journal→paketi geçici alanda doğrula→yalnız izinli sistem dosyalarını değiştir→migration→sağlık ve içerik koruma kontrolü→başarılı sürüm kaydını en son yaz. Kesintide yarım kurulumu başarılı göstermez; önceki sağlam sürüme geri dönme veya işlemi devam ettirme vardır. İkinci aynı update etkisiz ve güvenlidir. Eşzamanlı updater'lar kilitle ayrılır; aktif eski worker tamamlanmadan kesişen yazımlar uygulanmaz.

Kullanıcı notları, companion kişiliği, günlükler, knowledge, kullanıcı skill'leri, özel ayarlar ve kimlik bilgileri updater'ın değiştirebileceği dosyalar değildir. Sistem dosyasındaki kullanıcı değişikliği üçlü karşılaştırmayla görünür olur; desteklenen ayar birleştirmesi dışında çakışma korunur. Veritabanı migration'ı sürüm damgasına bağlı, idempotent ve yedekli olur. Eski handler/state geçişinde kayıt sınırı tutulur; eski günler yeniden işlenmez, iki özetleyici aynı olayı yazmaz.

Hook tanımı değişirse istemcinin gerekli güven incelemesi kullanıcıya açıkça bildirilir; güven kayıtları uydurulmaz. Dolayısıyla rutin güncelleme tek komut olur, her olası sürüm için sıfır etkileşim sözü verilmez. Tıklanabilir macOS/Windows/Linux kısayolları aynı komutu çağıran ince bir katman olabilir; önce updater doğrulanır.

## Uygulamadan önce sabitlenecek kabul senaryoları

1. Boş vault: üç çekirdek skill gerçekten kurulur ve keşfedilir; hazır ilk not/görev/receipt akışı tamamlanır.
2. Standart V2.3: kaynak içerik hashleri korunur; eski daily/knowledge/companion okunur; yeni ve eski writer çift çalışmaz.
3. Özelleştirilmiş V2: kullanıcı hook'u, skill'i ve ayarları korunur; yönetilen dosya çakışması görünür, sürüm başarılı işaretlenmez.
4. V3→V3 küçük sürüm: aynı komutla güncellenir; ikinci çağrı no-op; rollback önceki kod/şemayı geri getirir.
5. İndirme yarıda, bozuk paket, kopyalama arasında kesinti, yetersiz izin ve paralel güncelleme: veri kaybı ve yanlış başarı oluşmaz.
6. Windows/macOS/Linux: Unicode/boşluk yolları, CRLF/LF, sınırlı PATH ve symlink izni olmaması dahil kurulum+upgrade+rollback çalışır.
7. Güncelleme sonrası gerçek Codex/Claude/Antigravity oturumu mevcut notu ve skill'i kullanır; Codex Desktop için ayrıca kısa cold-session teslim kontrolü yapılır.

## Önerilen sıra

Önce core skill paketi ve ilk kullanım; sonra sürüm manifesti/ortak update aracı; ardından V2 migration ve kesinti/rollback matrisi; en son kısayol ve stable release. Mevcut CI başarıları bu yeni kabul senaryolarının geçtiği anlamına gelmez.

Desktop ve CLI aynı Codex yapılandırma katmanlarını paylaşır; aynı runtime'ın çalışması beklenir. Ayrı Desktop kontrolü yeni motor geliştirmek değil, açılan workspace/trust/oturum olaylarının gerçek teslimini doğrulayan kısa bir entegrasyon kontrolüdür. Kaynaklar: https://learn.chatgpt.com/guides/best-practices ve https://learn.chatgpt.com/docs/hooks .
