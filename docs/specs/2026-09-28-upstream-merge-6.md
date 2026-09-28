# Upstream birleştirme 6 (c4047fd): dört PR, tek çakışma, ve daily_log şema taşıması

Tarih: 2026-09-28 · Durum: TAMAMLANDI · İlgili: `2026-09-28-upstream-merge-5.md`,
`2026-09-28-unkarted-card-and-local-utc-divergence.md`

## Bağlam

Birleştirme-5'in ardından upstream `main` iki kez daha ilerledi. İlk etiketleme
(`da36d8c`) yapıldığında fork'un `main`'i senkrondu ve 761 test yeşildi; ama aynı
gün içinde upstream dört yeni PR birleştirdi. Ölçülen tablo:

```
        da36d8c (ikimizin ortak atası)
        ├── c4047fd  upstream/main  ← #135, #136, #132, #129
        └── 6cb4ef6'ye kadar bizim dalımız  ← #135 YOKTU
```

Bu, sessiz bir geri alma tuzağıydı: `main`'e fast-forward yapılsaydı #135'i geri
alırdık, çünkü bizim dalımızdaki `excerpt` #135 öncesi sürümüydü ve kimse çakışma
görmezdi.

| PR | İçerik |
|---|---|
| #135 | Journal özetinde tarihsiz en yeni giriş kaybolması — **#134, bizim bildirimimiz** |
| #136 | OpenCode 2.x eklenti API'si, 1.x ile birlikte (#133) |
| #132 | Hijyen opt-in'leri: kelime sınırı, klasör soruları, terfi (bakım düzeltmeleriyle) |
| #129 | Salt okunur doctor: sınır + kapanmış görevler |

#134'e `bakiabaci` yanıt verdi, yön kuralını netleştirdi ve PR'i kendisi yazdı;
`avenoxai` birleştirdi. Commit'te `Reported-by: Ahmet53535353` olarak anıldık.
**Bizden beklenen açık bir iş yoktu ve göndermedik.**

## Kuru deneme

`git merge-tree --write-tree HEAD upstream/main` — beş dosyada kesişim bekleniyordu,
kuru deneme **tek çakışma** gösterdi:

- `template/.claude/scripts/beyin_v3_hook.py` → **çakışma (içerik)**
- `README.md`, `docs/v3/PREFERENCES.md`, `scripts/beyin_v3.py`,
  `beyin_v3_companion.py`, `tests/v3_hook_test.py`, `tests/v3_preferences_test.py`
  → kendiliğinden birleşti

## Çakışmanın çözümü ve sıra kararı

İki taraf da aynı noktaya ekleme yapmıştı: biz günlük log bloğunu, upstream hijyen
sinyallerini. Çözüm ikisini de çalıştırmak — ama **hijyenden önce**.

Sebebi bir etkileşim, tesadüf değil: `session_start` bugünün günlük log dosyasını
yaratıyor. `folder_questions` vektörü onu tararsam dosya yeni bir kullanıcı
değişikliği olarak bildirilir. Hijyen önce koşunca tarama, oturumun açtığı dosyayı
görmeden çalışır.

`beyin_v3_companion.py` kendiliğinden birleşti ve **iki düzeltme de yerinde**:
upstream'in #135 kenar kuralı (satır 223) ve bizim `clip_cards` kuralımız. İkisi
farklı fonksiyonlarda ve aynı sınıfı iki ayrı dosyada çözüyorlar.

## Asıl karar: `daily_log` tercihi şemadan çıkarıldı

#132 bize bakan bir sonuç getirdi. Upstream'in kendi tuzağı: `hygiene` anahtarı her
tercih kaydında yazıldığı için, `beyin.py rollback` ile 3.5.1'e dönüldüğünde
`validate()` dosyayı reddediyor ve **doctor, preferences ve SessionStart hook'u
birlikte düşüyordu**. Upstream çözümü: opt-in'ler makine-yerel duruma gider.

Bizim `daily_log` anahtarımız aynı tuzağı birebir üretiyordu. Upstream'in yeni
testi bunu ölçtü ve birleşim ağacında tek kırılma olarak düştü.

Yamadan kaçındım: testi `released_keys`'e `daily_log` ekleyerek "düzeltmek", az önce
düzeltilen tuzağı geri getirmek olurdu. Bunun yerine upstream'in kendi yolunu
uyguladık:

- `.beyin-preferences.json` **yayımlanmış 3.5.1 şeması** ile birebir kaldı.
- Seçim `<state>/daily-log.json` dosyasına taşındı; tıpkı `hygiene.json` gibi.
- `validate()` eski dosyadaki `daily_log` anahtarını **okumaya devam eder**, yazmaz.
  Böylece o dosyayı taşıyan bir kullanıcının seçimi kaybolmaz.
- `--daily-log` artık vault tercih dosyasını hiç oluşturmaz (hijyen opt-in'leriyle aynı).
- Profil değişikliği seçimi sıfırlamaz, çünkü seçim artık profilde değil.

### Testin yakaladığı ikinci hata

`daily_log_chosen` eskiden "kullanıcı hiçbir şey belirtti mi" diye soruyordu ve
yanıtı, anahtarın dosyada **tesadüfen** bulunmasıydı — `validate()` her alanı
profilden doldurduğu için, kullanıcı günlük loga hiç dokunmasa da dosyada
bulunuyordu. Artık durum dosyası tek yanıt ve yalnız bu ayarı tutuyor; ilgisiz bir
tercih artık soruyu yanıtlamıyor.

Göçü yazarken bir hata yaptım ve yeni test onu yakaladı: legacy dosyadan okunan
**kapatma**, bir sonraki kayıtta anahtar düşünce kendiliğinden **açılıyordu** —
sessizce kullanıcının seçimi geri alınıyordu. `migrate_legacy_daily_log()` eklendi:
vault dosyası yazılmadan önce değer duruma taşınıyor. Test artık göçü de doğruluyor.

## Kalem 1: kenar kuralı ve dürüst bildirim

Upstream'in #135 çözümünü okuyunca kendi önceki düzeltmem **gereksiz temkinli**
bulundu. "Her başlık okunabiliyorsa tarihe göre sırala, aksi halde dosya sırasına
dön" kuralı gereksizdi: `SKILL.md:29` en yeni kartı üstte zorunlu kılıyor, yani
**yön biliniyor**. Upstream'ın Journal'da kullandığı kenar mantığı buraya birebir
uygulanır:

- Yalnız **en üst kartın** başlığı tarih okunamazsa o kart en yeni sayılır.
- Geri kalanlar tarihe göre sıralanır.
- Böylece ekleme sırası yazan bir ajanın en yeni kartı da kurtarılıyor — 0. durumda
  o kart düşüyordu.

Bildirim de düzeltildi. Sıra yalnız tarihten çıkabilir; bir başlık okunamadığında
`"older handoff cards"` diyerek **yaş uyduruyordu**. Artık iki biçim var:

- her başlık okunabiliyorsa → mevcut metin **birebir korunur** (`older` doğru çünkü
  sıralama tarihten geldi)
- okunamayan başlık varsa → biçim gerekliliğini (`YYYY-MM-DD HH:MM`) ve sıralamanın
  dosyadan geldiğini söyler

## Refspec

`remote.origin.fetch` yalnız `feat/explicit-memory-typing` dalını izliyordu. Bu yüzden
`origin/main` hiç tazelenmiyordu ve `--force-with-lease` her seferinde "stale info"
reddediyordu. Genişletildi (`+refs/heads/*:refs/remotes/origin/*`).

Bu kusurun ölçülebilir bir maliyeti vardı: push sırasında yerel `origin/main`
`f9a8b5f` gösterirken uzak `db1f23d`'deydi; senkronizasyonu yerel ref'e değil
GitHub'a sordum.

## Doğrulama

- Kuru deneme: 1 içerik çakışması.
- Hedefli (hook, hijyen, tercih, günlük log, companion, journal, opencode, ayrışma):
  75 + 11 yeşil.
- Birleşim sonrası tam paket: **974 passed, 1 skipped, 2324 subtests**.
- Kenar kuralı sonrası tam paket: **975 passed, 1 skipped, 2324 subtests**.
- Üç senaryo elle ölçüldü: tarihsiz üstte (kurtarıldı, sebep bildirildi), ekleme
  sırası + ortada tarihsiz (kurtarıldı), hepsi tarihli (eski metin korundu).

## Bu dalın durumu

`feat/memory-consolidation` kendi dalında kalıyor. Fork'un `main`'i **yalnız
upstream'in kendi commit'lerini** taşıyor (`c4047fd`, upstream ile birebir aynı);
105 commit'lik iş bu dalda. Upstream'e PR gönderilmedi.

## Kapsam dışı bırakılanlar

1. `stamp()` yalnız `YYYY-MM-DD` okuyor; `27.09.2026` ve `2026/09/27` kaçıyor.
   Devir kartları için biçim zorunlu (uyarı yolu bu), Journal için serbest
   (ayrıştırıcı yolu, upstream #134'te bekliyor).
2. Ekşeme sırası hâlâ bir sözleşme ihlali ve kenar kuralı onu kurtarmıyor; bildirim
   artık bunu söylüyor, çözümü yazarın.
