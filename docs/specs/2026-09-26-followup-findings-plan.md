# Bir aylık insan kullanımı E2E'si — takip planı (2026-09-26)

Kaynak: `docs/specs/2026-09-26-human-month-e2e.md` (ay sürücüsü ve 14 soru).
Buradaki kararlar, o raporun **düzeltilmemiş belgelenmiş bulgularını** tek tek
tekrar koda karşı sınadıktan sonra alındı. Sınamada **üç öneri yanlış çıktı**;
gerekçeleri aşağıda ayrı bölümde duruyor, çünkü kaybolması bir sonraki turda
aynı yanlış kararı yeniden üretmeye yol açar.

## Durum

| Bulgu | Konu | Karar | Durum |
| --- | --- | --- | --- |
| 1 | Sır süzgeci gerçek sağlayıcı anahtarlarını kaçırıyordu (P0) | düzelt | **kapalı** (aaa3c34) |
| 2 | Süreklilik kalıbı gerçek dönüş cümlelerini kaçırıyordu (P0) | düzelt | **kapalı** (aaa3c34) |
| 3 | Tip çıkarımı cevabı gizliyordu (P0) | düzelt | **kapalı** (aaa3c34) |
| 4 | Günlük log varsayılan kapalı ve keşfedilemez | **B-safe**: varsayılan açık + görünür uyarı | bu tur |
| 5 | Ekonomik profil dönen kullanıcıyı körleştirir | **B**: süreklilik istisnası, aralık kapısı da geçer | bu tur |
| 6 | Semantic fiş yalnız yeniden sıralıyor | **A-düzeltilmiş**: sözleşme yorumu, kullanıcı metnine dokunma | bu tur |
| 7 | Bağlam bütçesi daraldığında kurallar kırpılıyor (ölçümle düzeltildi) | kod değişikliği **yok**; davranışı kilitleyen test | bu tur |
| 8 | `dream` merge adayı ada bakıyor | faz-2 iş kalemi | kod yok |

---

## Düzeltme 1 — BULGU 4 bir belgelenmiş ürün kararını tersine çeviriyor

`docs/specs/2026-09-26-daily-log-design.md` bunu bilinçli seçmiş:

- `:4` "Kapsam: opt-in, varsayılan kapalı"
- `:52` "varsayılan `false`, üç profilde de"
- `:98` "**Installer'da soru/bayrak: ürün duruşu 'installer soru sormaz'**; açma
  tek seferlik `preferences --daily-log on` (karar A)"
- `:110` PR savunma satırı: "V3 oturum izini disipline bıraktı... **varsayılan
  kapalı**"

Varsayılanı açmak bu dört satırı da çürütür; installer'ın soru sormama duruşu
ve gerekçesi değişir. Bu yüzden "B-safe" seçildi: **varsayılan açık + ilk
oturumda tek satır görünür uyarı.** Böylece asıl bulgu (özellik keşfedilemiyor)
çözülür, installer duruşu korunur, açık-olsaydı sessizliği bırakılmaz.

Güvenli tarafı: `beyin_v3_preferences.py:52-53` `daily_log`'u (ve
`secret_filter`'ı) profil değişiminde koruyor, `validate` (`:20`) mevcut dosyayı
varsayılanlarla birleştiriyor. Yani **tercihini hiç belirtmemiş** kullanıcılar
yeni varsayılanı alır, **bilerek kapatmış** kullanıcılar kapatmış kalır. Sürpriz
yalnızca "hiç dokunmamış" kesimde ve o da ilk oturumda görünür bir satırla.

Uygulama: `preferences.py:11-13` üç profilde `daily_log=True`; `hook.py:336`
sonrası oturum çıktısına tek satır uyarı; `daily-log-design.md:4,52,98,110`
yeni karara göre güncellenir; `SKILL.md` tercih listesine ASCII `--daily-log
on/off` satırı (bulgunun ikinci yarısı: "CLI bayrağı var ama talimatta yok").

## Düzeltme 2 — BULGU 6'nın dayanağı yanlıştı

"Semantic arama etiketi fazla vaat ediyor" ifadesi **yanlıştı** ve geri
çekildi. Kullanıcıya dönük metinlerde `semantic` yalnızca bir **hafıza tipidir**
(`memory-types.md:6,21` "semantic — Kalıcı Bilgi / Gerçekler / Kimlik";
`beyin/SKILL.md:103` `type:"semantic"`). Arama modu vaadi hiçbir yerde yoktur.

Kalan tek sorun geliştirici içindir: `beyin_v3.py:820-828` fişi **yalnız** zaten
lexikal gelen adaylarla (`candidate_records`) çağırıp bir sıralama döndürüyor
ve RRF ile kaynaştırıyor; adı (`semantic_searcher`) geri çağırma ima ediyor.
Bu yüzden "akıllı kelimesel arama" gibi bir kullanıcı metni değişikliği
**gerekmiyor**; sözleşme yorumu ve spec notu yeterli.

## Düzeltme 3 — BULGU 7 iki kez ölçüldü ve **ikisi de yanlış çıktı**

"Hijyen tavanı" şudur: `beyin_v3_companion.py:13`
`LIMITS = {'Last-Session.md': 3000, 'Threads.md': 8000}` — yalnız **el devri**
dosyalarında. Mekanizma **salt-okur bir uyarıdır**: `hygiene()` (`:127-150`)
ölçer, `hygiene_notice()` (`:153-160`) tek satır "bunu `companion-compact` ile
küçült" der. **Kırpmaz, engellemez, bağlamı limitlemez.** Tavanı 8000→4000
yapmak yalnızca uyarıyı daha erken gösterir. (Kural, kimlik ve Journal'ın tavanı
yoktur; `:10-12` "kural, kimlik ve Journal tasarım gereği birikir, yalnız ölçülür".)

Kural #3'ün kırpılmasının gerçek sebebi başka: `FLOORS` (`:9`) = `Kurallar.md:
.4, Last-Session.md: .2` ve `:309` → `min(len(body), int(available *
FLOORS.get(name, 0)))`. **Taban aynı zamanda tavan.** Bütçe 5000 iken
`available = int(budget * .83) - fixed` (`:322`), Kurallar en fazla ~1600 karakter
alır; üç kural + başlıklar bunu aşınca bütçe hiç dolmadan 3. kural gider.

Sonra bu düzeltme de ölçüldü ve **ikinci bir yanlışlık** bulundu: su doldurma
zaten `NAMES` sırasında yürüyor (Core, Soul, Kurallar, Last-Session, Threads,
Journal, memory-types) ve turlar halinde dağıtıldığı için **Kurallar, Threads
daha büyürken kendi uzunluğuna kadar dolar**. Yani bir öncelik yeniden sıralaması
ölçülebilir hiçbir şeyi düzeltmiyor.

Gerçek ölçüm (3 kural × ~660 karakter, Threads ~6800, `v3_companion_budget_test.py`
fikstürü):

| bütçe | sonuç |
| --- | --- |
| 5000 (normal) | üç kuralın üçü de, devir kartı, kimlik ve Journal **tam**; hiç kırpma |
| 3000 | devir + kimlik tam; kural dosyasının **ortası** düşüyor, `[truncated: N characters omitted]` işaretiyle |
| 2000 (ekonomik) | en yeni kural ve devir kartı duruyor; ilk kural da düşüyor, yine işaretli |

Yani bulgu "Threads bütçeyi yiyor" değil, **"bütçe daraldıkça kural dosyası
sığmıyor"** — ve bu doğru davranış, tek kusuru görünmez olmasıydı (değil). Bu
yüzden **üretim kodunda değişiklik yapılmadı**; bunun yerine gerçek eşiği
kilitleyen bir test eklendi (`RulesSurviveLargeThreadIndexTest`): normal bütçede
hiçbir şey kırpılmaz, eşiğin altında kırpma görünür olur, en yeni kural ve devir
kartı korunur, konu dizini kuralların önüne geçmez.

---

## Uygulama sırası

1. **Push** — aaa3c34 (P0'lar + ay E2E + rapor). GitHub push protection commiti
   bir kez reddetti: test ağacında Stripe biçimli bir anahtar bitişik duruyordu
   (gerçek sır değil, Stripe'ın kamuya açık doküman örneği). Tüm test
   anahtarları sentetik ve parçalardan üretiliyor; ağaç push protection
   desenleriyle tarandı.
2. Bu spec.
3. BULGU 4 — kırmızı testler → `preferences.py` + `hook.py` + iki spec +
   SKILL.md → yeşil.
4. BULGU 5 — kırmızı testler → `hook.py:365`. Ekonomik profilde
   `interval_minutes=15` olduğu için istisna **aralık kapısını da geçmeli**;
   aksi halde `:370` "kontrol ertelendi" basıp yine bağlam vermez.
5. BULGU 6 — `beyin_v3.py:820` sözleşme yorumu.
6. BULGU 7 — kod değişikliği yok; kırpma eşiğini ve görünürlüğünü kilitleyen test.
7. BULGU 8 — kod yok, bu dosyada faz-2 kalemi olarak kalır.
8. Tam paket + ay sürücüsü yeşil → konu-bazlı commit → push.

ADIM 3 ve 4 **davranış değiştirir** (disk yazımı varsayılanı, ekonomik profilde
enjeksiyon); mevcut test beklentilerini kırarlarsa önce testleri kırmızıya
düşürmek, sonra düzeltmek gerekir.

## Faz-2'ye kalan iş

- **BULGU 6 tamamı:** gerçek bir geri çağırma fişi — embedding sağlayıcısı
  bağlanmalı ve fiş `candidate_only` havuzuna *yeni kayıt ekleyebilmeli*. Bugün
  yalnızca yeniden sıralar.
- **BULGU 8:** kalıcı "dismiss" listesi (`dream` adayı çözüldü diye işaretlenir)
  ve gövde benzerliği (bugün yalnız `_tokens(_title(...))`, yani dosya adı).
  Faz-1 salt-okur olduğu için erken; faz-2 mutasyonuyla birlikte.
