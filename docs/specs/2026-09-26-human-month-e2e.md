# Hızlandırılmış bir aylık insan kullanımı E2E'si (2026-09-26)

Bu, ürünü komut birim testi gibi sınamak yerine **bir insanın bir ay boyunca
projeyi nasıl kullandığını** taklit eden bir uçtan uca sınamadır. Persona: Zeynep,
serbest web geliştirici; proje "Kahve Dükkanı" (müşteri: Demir Kahve). 30 sanal
gün, 13 oturum, bir haftalık tatil boşluğu, ay sonunda konsolidasyon.

Sürücü: `tests/custom/v3_human_use_month_test.py` (deterministik, ~53 sn).

## Neden bir ay, neden "hızlandırılmış"

Saatle oynanamaz. Gerçek kod yolu (kurulum + `beyin.py` CLI + hook alt süreci)
bugünün saatinde çalışır; her sanal günün sonunda o günün üretilmiş
artefaktlarının tarihi geri alınır:

- **notlar**: `updated_at` zaten desteklenen bir metadata alanı, oluşturma anında
  veriliyor (dosya sonradan elle değiştirilmiyor);
- **receipt'ler**: dosyanın `created_at` alanı geri alınıyor ve yerel state'ten
  silinerek ürünün kendi "state reset -> diskten benimse" kurtarma yolu
  kullanılıyor. `daily/v3/<tarih>.md` projection'ı gerçekten o sanal tarihe
  düşüyor, `sync` temiz geçiyor (0 conflict, 0 warning);
- **günlük log**: bloklar `<!-- beyin-session:... -->` işaretine göre günlere
  bölünüyor, dosya adları sanal tarihe yazılıyor;
- **`dream.last_run`**: meta verisi elle yazılıyor (faz-2 mutating window henüz
  yok; kapı mantığı ölçülüyor).

Böylece ay sonunda motor **gerçekten yaşlanmış** bir vault görüyor: recency
sıralaması, 90 günlük prune yaşı ve günlük log takvimi gerçek tarihlerle çalışıyor.

## Takvim

| Gün | Oturum | Ne oldu |
| --- | --- | --- |
| 1 (2026-08-27) | kurulum, tanışma | Kimlik tercihleri Core.md'ye, proje notu, ilk görev (strict) |
| 2 (2026-08-28) | menü içeriği | **Kural #1** (mutlak tarih), kullanıcı günlük logu açtı |
| 4 (2026-08-31) | ödeme kararı | `semantic` karar notu, strict ödeme görevi |
| 6 (2026-09-02) | webhook hatası | `type: procedural` yöntem notu, öğrenim beyanı |
| 8 (2026-09-04) | hatırlama | "geçen hafta ne konuştuk", özet notu büyüdü |
| 9 (2026-09-05) | gizlilik | **Kural #2**, `visibility: private` fiyat notu, sır süzgeci açıldı |
| 11 (2026-09-07) | onay, geri alma | Kanıtsız `done` reddi, tercih `validity: rejected` |
| 12 (2026-09-08) | anahtar, tatil | Stripe anahtarı yapıştırıldı, ekonomik moda geçildi |
| 13-19 | — | Tatil: hiç oturum yok |
| 20 (2026-09-16) | dönüş | Tercihler normale döndü, aynı konuda ikinci not (merge adayı) |
| 21 (2026-09-17) | konsolidasyon penceresi | İlk `dream`; kapı reddi (receipt sayısı, 24 saat) |
| 24 (2026-09-20) | **Kural #3** | Toplantı saati, Threads.md 8000 sınırını aştı |
| 27 (2026-09-23) | büyüyen not | Özet notu 12000 karakter sınırını aştı |
| 29 (2026-09-25) | ay sonu | Rapor okundu, adaylar **elle** uygulandı, tekrar rapor temiz |

## Bir insanın soruları (14 soru, hepsi yeşil)

| # | Soru | Sonuç |
| --- | --- | --- |
| 1 | Notlarım kaydedildi mi? | 7 kayıt diskte, tarihleri doğru, aramada bulunuyor |
| 2 | Kurallarım yerinde mi, hatırlanıyor mu? | 3 kural da tarihli; yeni oturumda Core+Kurallar+Last-Session geliyor |
| 3 | Bir hafta sonra hatırladı mı? | Ödeme kararı, webhook yöntemi, gizlilik kuralı hepsi geri geliyor |
| 4 | Dağınıklık istendiğinde derlendi mi? | Rapor 3 adayı da gösterdi; uygulama sonrası adaylar boş; **rapor dışı hiçbir dosya değişmedi** |
| 5 | Dosyalarım duruyor mu? | Tohum notları bit düzeyinde aynı; kurulu kod/skill dosyası 0 değişti; companion'da yalnız 4 dosya (hepsi ajanın görevi) |
| 6 | Gizli veri sızmadı mı? | Private not hiçbir bağlamda yok; anahtar `[REDACTED]`, ham hâl vault'ta ve state'te yok |
| 7 | Kendi başına model/ağ çağırdı mı? | Hayır (doctor + dream raporları) |
| 8 | Doğal Türkçe sorular çalışıyor mu? | 4/4 |
| 9 | Günlük log takvimi doğru mu? | 11 günlük dosya sanal tarihle, ajanın yazdığı Özet korunmuş, tatil günü boş |
| 10 | Kanıtsız `done` geçiyor mu? | Reddedildi; kanıtla kabul, revision 2 |
| 11 | Geri alınan tercih ne oluyor? | Silinmiyor, güncel bağlama girmiyor, `history` okunabiliyor |
| 12 | Semantic arama nedir? | Vektör sağlayıcısı bağlı **değil**; RRF fişi çalışıyor, arıza kelimesel sırayı koruyor |
| 13 | Aramanın sınırları? | Gövde sözcükleridir, stem yok, tip filtresi motor düzeyinde (CLI bayrağı yok) |
| 14 | Ekonomik profil ne yapar? | Mesaj başına bağlam gelmez (belgelenen davranış) |

## Bulgular

### Düzeltilenler

**1. (P0, güvenlik) Sır süzgeci gerçek sağlayıcı anahtarlarını kaçırıyordu.**
G12'de kullanıcı bir Stripe anahtarı yapıştırdı, süzgeç açıktı (`secret_filter:
true`, profiller arasında da korunuyor) ve anahtar **düz metin** olarak receipt
kaynağına ve yerel veritabanına yazıldı. Sebep: gömülü desenler `sk-` (tire)
biçimini yakalıyor, Stripe'in gerçek biçimi `sk_live_`/`sk_test_` (alt çizgi).
`xox*`, `AIza`, `npm_`, SendGrid `SG.` ve JWT biçimleri de kapsam dışıydı.
Düzeltme: yedi desen eklendi, yalnız `sk_`/`rk_` için `live|test` segmenti
zorunlu tutuldu (aksi halde `sk_adi_soyadi` gibi bir form alanı yanlış eşleşirdi),
yanlış pozitif testleri yazıldı. `tests/v3_secret_filter_test.py`

**2. (P0, hatırlama) Süreklilik kalıbı gerçek dönüş cümlelerini kaçırıyordu.**
Tatilden dönen kullanıcı "bir haftalık tatilden döndük, neler yapmıştık" yazdı
ve otomatik bağlam **hiç** gelmedi: Core, Kurallar ve Last-Session sunulmadı.
Kalıp yalnız birkaç tam ifadeyi arıyordu (`ne yaptık`, `nerede kaldık`,
`son oturum`) ve diakritikler katlanmıyordu; ayrıca "ne yaptık" için İngilizce
karşılık yoktu. Düzeltme: tüm Türkçe diakritikler katlanıyor (NFKD + noktasız ı
haritalaması), kalıba "neredeydik", "kaldığımız yer", "son durum", "ne olmuştu",
"neler yaptık", "what did we do", "catch me up" gibi gerçek ifadeler eklendi.
`tests/v3_companion_test.py` (yeni `ContinuityRelevanceTest`)

**3. (P0, doğruluk) Tip çıkarımı sıradan kelimeleri yanlış türe bağlıyordu.**
Kullanıcı "müşteri fiyat listesi gizli mi" diye sordu ve **hiç sonuç gelmedi**:
`_tokens('listesi')` kökü "kontrol listesi" ile çakışıp soruyu prosedürel sanıyor,
`semantic` not elendi. İki düzeltme: (a) yalnız kendisi olarak duran, günlük
kelimelerle çakışmayan ipuçları bırakıldı (`kontrol listesi` -> `kontrol`,
`belge` çıkarıldı, `adımlar` eklendi); (b) asıl savunma: **çıkarımlı kapı sonucu
tamamen boşaltıyorsa kapısız aramaya geri dönülüyor** — açık `types=` filtresi
asla gevşemez, yalnız tahmin gevşer. `tests/custom/v3_type_inference_test.py`

### Belgelendi, düzeltilmedi (gerekçesiyle)

**4. Günlük log varsayılan olarak KAPALI ve SKILL'de hiç anlatılmıyor.**
`session_start/session_end` `daily_log` ayarı kapalıysa hemen dönüyor; CLI'de
`preferences --daily-log on` var ama SKILL'in tercihler listesinde yok. Yani bir
kullanıcı bu özelliği kendi başına keşfedemez. E2E sırasında kullanıcı G1 sonunda
açtı; ilk oturum (açıldığı gün) kaydedilmedi. Karar: SKILL'e eklemek ayrı bir
iş kalemi; ölçüm haftası öncesi ayrı bir değişiklikle ele alınacak.

**5. Ekonomik profilde mesaj başına bağlam gelmez (tasarım, doğru çalışıyor).**
`context_mode='session'` yalnız oturum başında bağlam veriyor. Bir hafta sonra
dönen kullanıcı ekonomik moddaysa hiçbir şey gelmiyor; profili normale çevirince
aynı cümle tüm companion kaynaklarını getiriyor. İnsan davranışı olduğu için
sürücüde her iki hâl de ölçülüyor.

**6. "Semantic arama" bugün kelimesel.** Kurulumda `semantic_searcher` her zaman
`None`; hiçbir embedding sağlayıcısı bağlı değil. Arama FTS5/bm25 + RRF fişi.
Ölçülen mimari sınır: fiş **yalnız lexikal olarak gelen aday havuzunu** görüyor,
yani sıralayabiliyor ama yeni bir kaydı aday havuzuna **ekleyemiyor**. Saf
semantik hatırlama bu yüzden bugün mümkün değil; bu, faz-2 için ön koşuldur.

**7. Bağlam bütçesi daraldığında kural dosyası kırpılıyor (sonradan ölçümle düzeltildi).**
Normal profilde 5000 karakterlik bütçede üç kuralın üçü de, devir kartı ve kimlik
dosyası **tam** geliyor; konu dizini (`Threads.md`) onları aç bırakmıyor, çünkü su
doldurma `NAMES` sırasında yürüyor ve kurallar önce dolar. Kırpma yalnızca bütçe
daraldığında (3000'de orta kural, ekonomik profilin 2000'inde ilk kural) oluyor ve
her seferinde `[truncated: N characters omitted]` işaretiyle **görünür** kalıyor. Yani
bulgu "bütçeyi Threads yiyor" değil, "bütçe daraldıkça kural dosyası sığmıyor"; bu
davranış doğru, eşiği `v3_companion_budget_test.py` kilitliyor. Raporun ilk yazımında
iddia fazla güçlüydü ve ölçümle düzeltildi.

**8. `dream` merge adayı dosya adına bakar.** Yinelenen notu birleştirip yerine
bir işaretçi not bırakmak adayı temizlemiyor; dosya gerçekten kaldırılınca
temizleniyor. Faz-2 için not: adayın "çözüldü" durumu tutulmuyor.

Ayrıca: `dream` bayrağı `--dry-run` değil, düz `dream`; faz-1 hiçbir şey
yazmadığı için ayrı bir kuru-koşum bayrağı yanıltıcı olurdu.

## Nasıl koşulur

```sh
python3 -m unittest tests.custom.v3_human_use_month_test   # ~53 sn, 14 soru
python3 -m unittest discover tests -p "*test.py"            # 792/792
```
