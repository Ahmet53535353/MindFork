# Bizim düzeltmelerimiz — upstream merge bunları sessizce düşürebilir

`git log upstream/main..HEAD` bu dalın neyi değiştirdiğini söyler, **neyin
korunması gerektiğini** söylemez. Bu dosya ikinci sorunun cevabıdır.

`measure_merge.py --only coverage` bu tabloyu okur ve her satır için `tests/`
altında **davranış işaretini** arar. Bulamazsa satırı eksik olarak raporlar:
testi olmayan bir düzeltme, merge'de kaybolursa kimse fark etmez.

> **İşaret sütunu sembol değil, davranış işaretidir.** 2026-10-15'te
> `VALID_MEMORY_TYPES` için grep yapıldı, sıfır test çıktı ve boşluk sanıldı.
> Oysa tip kapısının davranışı 6 test dosyasında kapsanıyordu. Sembol adı,
> davranışın kapsanıp kapsanmadığını söylemez.

> **Koşul sütunu boş bırakılmaz.** 2026-10-18'de ölçüldü: "Ertelenen kontrol uyarısı"
> satırı testli, yerinde ve kapsanmıştı — ama tetik koşulu (`continuity and not due`)
> koddan düştüğü için davranış neredeyse her `UserPromptSubmit` turunda çalışıyor,
> 156 karakter gider harcıyor ve upstream'in dedupe sözleşmesini kırıyordu. Ne kaybolmuş
> ne de kapsamasızdı: **genişlemişti.** Kapsama raporu bunu göremez; sapma satırı
> "ne zaman tetiklenir" bilgisini taşırsa gözden kaçmaz.

| düzeltme | davranış işareti | koşul (ne zaman tetiklenir) | gerekçe |
|---|---|---|---|
| Fork kanalı |  `OFFICIAL_WEBS`  | her `check()` / `update` çağrısında; güncelleme anında |  Upstream'da `push` yetkisi yok (`pull`). Yayınlama yetkisi olan tek depo bu fork; updater buraya bakmalı. `OFFICIAL` = "en yeni sürüm hangi depoda", `OFFICIAL_WEBS` = "hangi asset URL'lerine güvenilir" — ayrı işler, karıştırılırsa check() upstream'i okumaya devam eder.  |
| Tip sistemi |  `episodic`  | arama anında tür kapısı uygulanırken (soft gate + yeniden deneme) |  Bellek türleri (`episodic`/`semantic`/`procedural`) ve arama anında uygulanan tür kapısı bizim eklentimiz; upstream saf Python BM25 kullanıyor, tür kavramı yok. Kapı yanlış tahmin yaptığında yeniden denenmesi gerekiyor (çıkarılan bir tahmin sonucu boş döndürmemeli).  |
| FTS imzası |  `records_fts`  | indeks şeması/tokenizer değişince; imzasız indekste her açılışta |  FTS5 indeksi hızlandırıcı olarak bizim eklentimiz. İmza (`FTS_PARAMS`), şema veya tokenizer değişince artmalı; eski veritabanı bir sonraki açılışta kendini yeniler. Sıralamayı FTS değil Python BM25 yapar.  |
| Projection guard |  `'knowledge/index.md': False`  | kaynak taraması sırasında, `knowledge/index.md` ve `log.md` için |  `PROJECTION_GUARD`, `knowledge/index.md` ve `log.md`'yi birikim hedefi olmaktan çıkarır. **Bu satır 14 gün testsiz kaldı** (2026-09-26 eklendi, test 2026-10-10'da geldi). O boşlukta bir merge guard'ı sessizce düşürdü ve yalnız AST taraması yakaladı. Kapsama ancak 2026-10-10'da kapandı.  |
| Tetikleyici kaynağı |  `Tetikleyici.md`  | her açılışta ve süreklilik turunda (`NAMES` içinde olduğu için) |  `Tetikleyici.md` süreklilik kaynağı olarak `NAMES`'te; Gradle tetikleyicisi (`./gradlew --stop`) her oturumda görünür kılıyor. Upstream bu dosyayı `NAMES`'ten çıkarmıştı — bu bir sapma, kasıtsız kabul edilmemeli.  |
| Minecraft tespiti yokluğu |  `minecraft_project`  | her `context(cwd=)` çağrısında (bulunmadığı doğrulanır) |  2026-10-15'te kaldırıldı. Yokluk sözleşmesi: `minecraft_project`, `tetikleyici_katman` ve `context(cwd=)` **yeniden doğmamalı**. Upstream'da bu kural dosyası yok; bir merge onu geri getirirse kasıtsız projeye özel kural yeniden doğar.  |
| Günlük logun yokluğu |  `beyin_v3_sessionlog`  | hiçbir koşulda: yokluk sözleşmesi (modül ve import bulunmamalı) |  2026-10-15'te Ahmet kapatmayı tercih etti, özelliği de istemedi (`c6217f8`). `beyin_v3_sessionlog.py` **tümüyle** silindi, `daily/log/` altında kayıt veya iz kalmadı; `validate()` artık tanımadığı anahtarı reddetmiyor. Anahtarlarla kapatmak yetmezdi: `daily-log.json` kalsa bir gelecek sürüm modülü geri getirdiğinde log kendiliğinden açılırdı. Sözleşme `tests/custom/v3_daily_log_removed_test.py` ile korunuyor (modülün ve importun yokluğu).  |
| Özet çiti muhasebesi |  `bilgi dizgisi`  | her `submit_receipt` çağrısında, özette çit bulunduğunda |  2026-10-17'de kapanmayan çitli özet indeksleri okunmaz yapıyordu: `%93`'e varan satırlar kod bloğu sanılıyordu (`50b9084` + `7424c9f`, `5c69da4`, `8d8c684`). Çit muhasebesi CommonMark'a göre düzeltildi: geri al çakışmasında girinti kaybı, kacışta tek ters bölü. Kural **boru hattının ilk ucunda** (`submit_receipt`) uygulanır, çünkü receipt değiştirilemez (`docs/v3/RUNTIME.md`, amend yolu yok) — hasar kalıcı olurdu.  |
| Genişletilmiş kapı |  `beyin-gate-`  | her kaynak taramasında; bozuk dosya varsa yükseltir, `Last-Session`/`Threads` yazılmadığı için giriş denetimi yok |  2026-10-17'de kapı daraltması kaldırıldı (`7fba1c2`). Gerekçe ölçümlü: tüm vault taraması 45 ms (278 dosya, 2.1 MB), daraltmanın maliyet gerekçesi yoktu. `Last-Session.md` ve `Threads.md` için motor **hiçbir yazma çağrısı yapmıyor**, dolayısıyla girdi denetimi uygulanamaz; giriş kapısı yoksa tek ag çıktı taraması kalır. Upstream bu dosyaları hâlâ dışarıda tutuyor olabilir — sapma, kabul edilmiş.  |
| Ertelenen kontrol uyarısı |  `Automatic check deferred`  | yalnız `continuity and not due`: süreklilik turu **ve** otomatik kontrol aralıkta ertelenmiş |  2026-09-27'de eklendi (`071ab43`): dönen kullanıcı "bir haftalık tatilden döndük" dediğinde companion dosyaları taze ama indeksli hafıza eski olabiliyor. **Sapma daraltıldı (2026-10-18):** koşul yalnız süreklilik turunda (`continuity and not due`). Koşul düşünce uyarı neredeyse her `UserPromptSubmit` turunda 156 karakter bütçe harcıyor ve upstream'in dedupe sözleşmesini (#363, "yeni bir şey yoksa çıktı da yok") kırıyordu. Upstream'da böyle bir uyarı yok; otomatik kontrol `SessionStart`'ta her zaman çalıştığı için açılışta hiç görünmez.  |

## Bu tablo neden elle güncellenmiyor

Satırlar kapsama ölçümüyle üretilir. Yeni bir yerel düzeltme eklediğinde:

1. İkinci sütuna o davranışı **testlerde aranabilir** bir işaret koy.
2. **Üçüncü sütuna koşulu yaz: ne zaman tetiklenir?** Koşulu olmayan bir satır, davranış
   genişlediğinde sessizce yanlış ölçülür (yukarıdaki 2026-10-18 örneği).
3. Dördüncü sütuna gerekçeyi yaz.

İkinci sütun `tests/` altında bulunamıyorsa skill bunu raporlar.

Satır silmek doğru değildir: bir düzeltme geri alındıysa tablo da düşer, ama
o düzeltmenin **yerine ne geldiği** yukarıdaki gerekçede yazılır.

## Tablo bayatlar

2026-10-18'de tablo, aynı dönemde yapılan üç düzeltmeyi (günlük logun yokluğu, özet çiti
muhasebesi, genişletilmiş kapı) içermiyordu; ancak `git log upstream/main..HEAD`'e bakmak
onları göstermişti. Yeni satır ararken önce son merge'den bu yana gelen yerel commit'lere
bak: `git log --oneline <son-merge>..HEAD`.