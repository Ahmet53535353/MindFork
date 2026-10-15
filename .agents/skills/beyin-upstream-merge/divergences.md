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

| düzeltme | davranış işareti | gerekçe |
|---|---|---|
| Fork kanalı | `OFFICIAL_WEBS` | Upstream'da `push` yetkisi yok (`pull`). Yayınlama yetkisi olan tek depo bu fork; updater buraya bakmalı. `OFFICIAL` = "en yeni sürüm hangi depoda", `OFFICIAL_WEBS` = "hangi asset URL'lerine güvenilir" — ayrı işler, karıştırılırsa check() upstream'i okumaya devam eder. |
| Tip sistemi | `episodic` | Bellek türleri (`episodic`/`semantic`/`procedural`) ve arama anında uygulanan tür kapısı bizim eklentimiz; upstream saf Python BM25 kullanıyor, tür kavramı yok. Kapı yanlış tahmin yaptığında yeniden denenmesi gerekiyor (çıkarılan bir tahmin sonucu boş döndürmemeli). |
| FTS imzası | `records_fts` | FTS5 indeksi hızlandırıcı olarak bizim eklentimiz. İmza (`FTS_PARAMS`), şema veya tokenizer değişince artmalı; eski veritabanı bir sonraki açılışta kendini yeniler. Sıralamayı FTS değil Python BM25 yapar. |
| Projection guard | `'knowledge/index.md': False` | `PROJECTION_GUARD`, `knowledge/index.md` ve `log.md`'yi birikim hedefi olmaktan çıkarır. **Bu satır 14 gün testsiz kaldı** (2026-09-26 eklendi, test 2026-10-10'da geldi). O boşlukta bir merge guard'ı sessizce düşürdü ve yalnız AST taraması yakaladı. Kapsama ancak 2026-10-10'da kapandı. |
| Tetikleyici kaynağı | `Tetikleyici.md` | `Tetikleyici.md` süreklilik kaynağı olarak `NAMES`'te; Gradle tetikleyicisi (`./gradlew --stop`) her oturumda görünür kılıyor. Upstream bu dosyayı `NAMES`'ten çıkarmıştı — bu bir sapma, kasıtsız kabul edilmemeli. |
| Minecraft tespiti yokluğu | `minecraft_project` | 2026-10-15'te kaldırıldı. Yokluk sözleşmesi: `minecraft_project`, `tetikleyici_katman` ve `context(cwd=)` **yeniden doğmamalı**. Upstream'da bu kural dosyası yok; bir merge onu geri getirirse kasıtsız projeye özel kural yeniden doğar. |

## Bu tablo neden elle güncellenmiyor

Satırlar kapsama ölçümüyle üretilir. Yeni bir yerel düzeltme eklediğinde:
beşinci sütuna (gerekçe) yaz, ikinci sütuna o davranışı **testlerde aranabilir**
bir işaret koy. Üçüncü sütun `tests/` altında bulunamıyorsa skill bunu raporlar.

Satır silmek doğru değildir: bir düzeltme geri alındıysa tablo da düşer, ama
o düzeltmenin **yerine ne geldiği** yukarıdaki gerekçede yazılır.