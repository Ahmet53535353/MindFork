---
name: beyin-doktor
description: Beynin gerçekten çalışıp çalışmadığını, kaynak güncelliğini, hook/worker durumunu, skill çakışmalarını ve güncelleme sorunlarını denetle. Sağlık kontrolü ve hafıza arızasında kullan.
---

# Beyin doktoru

Vault kökündeki `beyin.py` ile çalış. macOS/Linux: `python3 beyin.py doctor`; Windows: `py -3 beyin.py doctor`. Eski Bash hook listelerini veya başka bir kullanıcının yollarını kopyalama.

Çıktıdaki sürüm, bekleyen/başarısız işler, son sync, kaynak çakışmaları ve skill durumunu oku. Komut exit 0 olsa bile boş lifecycle geçmişini 'istemci bağlantısı doğrulandı' diye yorumlama. Hata loglarını veya özel notları sohbete dökmeden, arızayı ve en küçük düzeltmeyi açıkla.

Kaynak değişikliği indekslenmemişse `python3 beyin.py sync`; skill dosyaları farklıysa `python3 beyin.py skill-sync` ile kontrollü uzlaştır. İki taraf da değişmişse dosyaları koru ve hangi sürümün seçilmesi gerektiğini belirt. Güncelleme yarım kaldıysa `beyin-guncelle` yolunu kullan; runtime veritabanını veya kullanıcı dosyalarını silerek sağlık göstergesini yeşile çevirme.

İstemci bağlantısını doğrulamak gerektiğinde özel veri içermeyen bir deneme notu kullan. Yeni gerçek oturumda yalnız hook bağlamından bu nottaki bilgiyi istemek, dosyanın varlığını kontrol etmekten daha güçlü kanıttır. Codex'te doğru proje ve `/hooks` güvenini, Claude'da yeni proje oturumunu, Antigravity headless kullanımında `--add-dir VAULT` bağını, OpenCode'da vault klasöründe açılmasını ve `.opencode/plugins/beyin-v3.js` dosyasını kontrol et. Güven hashlerini yazma ve bypass ile alınan sonucu normal kurulum kanıtı sayma.

Kullanıcıya üç şey söyle: çalışan kısım, doğrulanmamış/bozuk kısım, varsa tek sonraki düzeltme. Ham JSON yerine kısa ve somut bir sonuç ver. Kullanıcının mevcut onayı güvenli düzeltmeyi kapsıyorsa gereksiz tekrar onay isteme.
