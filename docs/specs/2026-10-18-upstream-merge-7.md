# Upstream birleştirme 7 (d9aa301): 67 commit, yedi dosya, bir sözün bozulması

Tarih: 2026-10-18 · Durum: TAMAMLANDI (yayın yok) · İlgili: `2026-09-28-upstream-merge-6.md`,
`.agents/skills/beyin-upstream-merge/divergences.md`

## Bağlam

Upstream `main` 2026-10-18'de `d9aa301`'deydi (`VERSION` 3.11.0), bizim dal `79f6c75`'te
(`VERSION` 3.13.0). Ortak ata `4645451`. Ölçülen ayrışma: **67 commit geride, 97 ileride**.

Yedi gün önce (2026-10-16) yaptığımız upstream birleştirmesinin (merge-7'nin öncüsü, `7fba1c2`)
ardından upstream dört dalga daha ilerlemişti. Altı commit'imiz upstream'ta **ayrı PR olarak da**
merge edilmişti:

| Bizim | Upstream | Konu |
|---|---|---|
| `d80c12d` | `20af941` | senkron gecikince arama düşmüyor (#365) |
| `d9cc354` | `19bce72` | eski bilgi bağlantısı öğrenim sayılmıyor (#369) |
| `f3b4790` | `a00d590` | pending index okuması hook bütçesinde (#370) |
| `ffb1212` | `933b92f` | Bash ile koşan `beyin.py` receipt penceresini açar (#212) |
| `b276fc4` | `7093781` | bilgi notu yazımı düzenleme penceresini sayar (#327) |
| `a33e168` | `076a4b4` | yavaş senkron etiketli önceki indeksi sunar |

Yani aynı düzeltmeler iki yerde birden yaşıyordu. Her dalga bu çiftleri büyüttü; bu yüzden
merge bugün yapıldı.

Sürüm hattı çakışması ayrı bir konuydu: iki taraf da **kendi 3.11.0'ini** yayımlamıştı
(bizimki 2026-10-15'te, upstream'inki 2026-10-17'de) ve dosya adı tek.

## Kuru deneme

`measure_merge.py --only preflight` → iki refspec de tam (`+refs/heads/*`).
`measure_merge.py --only merge` → **7 dosyada çakışma, 12 hunk**:

| Hunk | Biz | Onlar | Dosya |
|---|---|---|---|
| 1 | 1 | 1 | `VERSION` |
| 1 | 46 | 144 | `docs/v3/releases/3.11.0.md` |
| 1 | 231 | 144 | `template/.agents/skills/beyin/SKILL.md` |
| 1 | 1686 | 1419 | `template/.claude/scripts/beyin_v3.py` |
| 3 | 872 | 677 | `template/.claude/scripts/beyin_v3_companion.py` |
| 2 | 688 | 719 | `template/.claude/scripts/beyin_v3_hook.py` |
| 3 | 1097 | 1203 | `tests/v3_hook_test.py` |

Taban: `pytest tests/ -q` → **1855 passed, 27 skipped, 5848 subtests** (22:44). Yeşil.

Kapsama (Adım 3): `divergences.md` üç yerel düzeltmeyi içermiyordu; üç satır eklendi
(günlük logun yokluğu, özet çiti muhasebesi, genişletilmiş kapı). Rapor **9/9 ok**.

## Çakışma niteliği

Yedi dosyanın beşi **mekanik**: iki tarafın değişikliği birbirinin yerine geçmiyordu, ikisi de
durdu. İkisi **anlamsal**ydı: aynı karar yüzeyinde (açılışta ne kadar yer, hangi sürüm
sayılır) iki taraf farklı karar vermişti.

- `VERSION` + `docs/v3/releases/3.11.0.md`: sürüm hattı kararı. Ahmet'in onayıyla **3.14.0**
  kararı alındı (upstream'in 3.12/3.13'ü ile çakışmasın diye atlandı); `VERSION` merge
  anında 3.13.0'da kaldı çünkü merge yayın değildir. İki 3.11.0 tek dosyada iki bölüm olarak
  duruyor, ikisi de kendi deposunun karşılaştırma bağlantısıyla.
- `beyin_v3_companion.py`: upstream `context()`/`companion()` imzalarını değiştirdi
  (`report=` parametresi, dönüş `tuple`), biz kart kesme mantığımızı ve bütçe tavanımızı
  taşıyoruz. Aşağıda ayrı bölüm.

## Adımlar

1. `git fetch upstream` → yerel `upstream/main` bayattı (5328094), gerçek 67 commit ölçüldü.
2. Taban test sayısı yazıldı (1855/27/5848).
3. `divergences.md` güncellendi, kapsama raporu 9/9.
4. `git merge --no-commit --no-ff upstream/main` → ölçülen 7 dosya çıktı, başka çakışma yok.
5. Çakışmalar çözüldü:
   - `VERSION` → 3.13.0.
   - `docs/v3/releases/3.11.0.md` → iki sürüm tek dosyada, 3.14.0 kararı başlıkta.
   - `template/.claude/scripts/beyin_v3.py` → bizim taraf (tip sistemi + hybrid RAG); upstream'in
     `__init__` değişikliği bizimkinin alt kümesiydi.
   - `beyin_v3_hook.py` → upstream'in dedupe reset bloğu **alındı** (yeni özellik, bizde yok),
     pending uyarısı bizim bileşik sürümüyle kaldı (upstream'in cümlesi bunun alt kümesiydi).
   - `template/.agents/skills/beyin/SKILL.md` → upstream'in yeni kuralları (proje kuralı hedefi
     #375/#376, kapsam etiketi, kişi notu) + bizim metinlerimiz. Upstream'in tek satır paragraf
     stili alındı; bizim "günlük log" cümlelerimiz zaten ölüydü (aşağıda).
   - `tests/v3_hook_test.py` → iki tarafın testi de durdu (`slow_sync_hook(exclusive=)`).
6. Anlamsal çözüm: `beyin_v3_companion.py` (aşağıdaki bölüm).
7. Doğrulama (aşağıdaki bölüm).
8. Commit, push, bu not, receipt.

## Anlamsal denetim: doktorun sözü ve ertelenen kontrol uyarısı

Upstream'in `#374` değişikliği doktora bir **söz** ekliyor: "Kurallar.md açılışta kırpılıyor:
kural metni N karakter; açılış bu ayarlarla en fazla M karakterini **tam** gösterir." M, kuralların
tam olarak geleceği en büyük boyut olmalı.

Bu fork'ta ölçtüğümüzde söz tutmuyordu:

| | Upstream ağacı (d9aa301) | Bu fork (merge öncesi) |
|---|---|---|
| Doktorun payı (45.618 karakterlik dosyada) | 3755 | 3264 |
| O pay kadar dosya konunca | 3755 gelir, `clipped: False` | **3108 gelir**, `clipped: True` |
| Upstream'in `#374` testi | geçer | kırılır |

Açılışta kurallara 156 karakter eksik geliyordu. Ölçtüğümüz fark tam olarak **156**'ydı ve bu,
bizim eklediğimiz "Automatic check deferred by your interval preference" uyarısının uzunluğuydu.
Doktor açılışı 412 karakter giderle ölçüyordu, hook 568 ile. Kalan aday tek taneydi: yedinci
companion kaynağı (`Tetikleyici.md`) ve merge-5'te değişen FLOORS tablosu — ama ölçüm onu
suçlamadı, çünkü doktorun **saydığı gider** yanlıştı.

### Gerçek neden: koşulu olmayan bir uyarı

`071ab43` (2026-09-27) bu uyarıyı `continuity_turn and not due` koşuluyla eklemişti: yalnız
"son oturumda ne yaptık" gibi bir süreklilik sorusunda, otomatik kontrol ertelendiyse. Sonradan
`continuity_turn` koddan düştü, koşul `if not due` olarak kaldı. `claim_check` her oturum
başında kontrolü **her zaman** çalıştırdığı için (`event != 'SessionStart'` dalında aralık
varsa `False`), uyarı yalnız `UserPromptSubmit` turlarında ve **neredeyse her turda** çalışıyordu:
her turda 156 karakter gider, her turda boş da olsa çıktı.

Sonucu ölçtük: `tests/v3_context_dedupe_test.py`'de upstream'in beş testi kırıldı. Hepsi aynı
sözü söylüyor — `#363`'ün sözleşmesi: "yeni bir şey yoksa çıktı da yok" (`{}`).

Çözüm: koşul geri geldi. `continuity = bool(relevant(prompt_text(payload)))` — `relevant` zaten
companion bağlamını hangi turlarda gönderdiğini belirleyen işaret (#145), yani
`continuity_turn`'un bugünkü karşılığı. Süreklilik turu uyarıyı alır, sıradan tur sessiz kalır,
`SessionStart`'ta uyarı zaten hiç görünmez. Upstream'in `context()` imzası, `rules_opening` ve
`report=` parametresi **değişmedi**; doktor tarafında tek satır değişiklik de kalmadı.

### Doğru çözümü iki kez yanlış buldum

1. İlk teşhis: "upstream'in formülü yedinci kaynakta kırılıyor, sabit noktaya çözmek gerek."
   Sabit nokta hesabını yazdım; dokuz bütçe/vault kombinasyonunda ölçtüm, **gereksiz** olduğunu
   gördüm (pay her kombinasyonda zaten tam gelen boyuttu) ve sildim. Doğru gözlem, yanlış gerekçe.
2. İkinci teşhis: "doktor uyarının giderini saymıyor, ortak `opening_warning(pending, due)` ile
   sayalım." Bunu yazdım ve upstream'in testi yeşillendi. Ama `claim_check`'i okuyunca gördüm ki
   otomatik kontrol `SessionStart`'ta **her zaman** çalışıyor; yani doktorun açılışta sayması
   gereken bir uyarı yok. Gerçek söz, uyarının **hiç görünmemesi gerektiği**, yani koşulun
   daraltılmasıydı. Yazdığım boru hattı (`opening_warning`, `rules_opening(warning=...)`,
   doktorun `warning=` argümanı) ölçümün işaret ettiği yeri sarmalıyordu; **tamamı geri alındı**.

Ders (aynı gün üçüncü kez): sonucu doğru okudum, gerekçeyi iki kez değiştirdim. Ölçüm
kırmızıyı gösterdiği yeri değil, **kırmızının nerede olmadığını** da göstermeli: yeşil test
"doğru yer" demek değil.

### Doğrulama

- Taban: **1855 passed, 27 skipped, 5848 subtests** (22:44).
- Merge sonrası tam paket (ilk koşu): **6 failed, 2082 passed, 30 skipped, 6024 subtests** (24:45).
- Kırılmalar ve düzeltmeleri:
  1. `v3_instruction_block_test` — bizim SKILL.md'den kalan, elle satıra bölünmüş tek paragraf
     (upstream #361 tek satır istiyor). Düzeltildi; ikinci ihlal de upstream metninde değil,
     bizim AutoDream/konsolidasyon paragrafımızdaydı (HEAD'de 82, CLAUDE.md'de 10 satır
     sarılmıştı; merge upstream'in düzeltilmiş metnini aldı, bizimkini 3 satır kaldı).
  2. `v3_context_dedupe_test` (5 test) — ertelenen kontrol uyarısı her turda çalışıyordu;
     koşul daraltıldı (yukarıda).
- Düzeltmelerden sonra yalnız **düzeltmeye dokunan paketler** koşuldu:
  - `v3_context_dedupe_test.py` → 25 passed
  - `v3_instruction_block_test.py` + `v3_daily_log_removed_test.py` → 25 passed, 20 subtests
  - `v3_companion_snapshot_rules_test.py` + `v3_companion_rules_share_test.py` → 9 passed
  - `v3_hook_test.py`, `v3_strict_context_test.py`, `v3_companion_{test,budget,multicard,hygiene}_test.py`,
    `custom/v3_human_use_month_test.py`, `v3_preferences_test.py` → 208 passed, 131 subtests
- `python3 scripts/evaluate_v3.py` → geçti (çıkış 0). CI'ın ikinci kapısı.
- `measure_merge.py --only coverage` → **10/10 ok**, 0 korumasız (merge sırasında dört satır eklendi).
- Kanal ölçümü: `releases.check(vault)` → `up_to_date`, current 3.13.0, latest 3.13.0,
  `OFFICIAL` = `Ahmet53535353/MindFork`.
- Mutasyon kanıtları:
  - `if continuity and not due` → `if not due`: 6 test kırmızı.
  - SKILL.md'ye ölü günlük log paragrafı/tercih satırı geri: kaldırma testi kırmızı.

## Kapsam dışı bırakılanlar

1. `template/.claude/scripts/_portalock.py` docstring'i "daily-log / knowledge pipeline"
   diyor. Upstream'in kendi metni (Windows destek PR'ı), bizim ölü talimatımız değil; yazım
   düzeltmesi yapılmadı.
2. Upstream'in `3.12.0`/`3.13.0` release'leri bu fork'un kanalında görünmez. Bilinen ve kabul
   edilmiş; fork kendi hattını 3.14.0'dan sürdürüyor.
3. `bukkit + yakala` tarafının upstream yeni özellikleri (Windows ekran yakalama, X/Instagram
   gönderi, Wayland pano) bu merge ile **geldi** ama bu vault'ta denenmedi; davranışları
   ayrı bir iş birimi.
4. `docs/v3/releases/3.11.0.md` iki sürümü bir arada taşıyor. Upstream'in yayımlanmış notu
   değişmedi ama bizim dosyamız artık iki sürümün notu; 3.14.0 notu bunu devralacak.
5. Tam paket, düzeltmelerden sonra baştan koşulmadı (süre). Yalnız düzeltmeye dokunan paketler
   koşuldu; liste burada. Bir sonraki merge'de tam paket tabanı yeniden alınacak.

## Süreçte bulunan kendi hatalarım

1. **`divergences.md`'ye yanlış gerekçe yazdım.** Günlük logun yokluğu için "testi yok" dedim;
   ölçüm tersini söyledi: `measure_merge.py` `tests/` altını rglob ile tarıyor, `tests/custom/`
   altındaki `v3_daily_log_removed_test.py` sözleşmeyi zaten koruyordu. Elle `grep tests/*.py`
   sığ tarama yapmıştım. Düzeltildi, satır gerekçesi testin adına göre yeniden yazıldı.
2. **Teşhisi sezgiyle koydum.** "Upstream'in formülü yedinci kaynakta kırılıyor" dedim ve sabit
   nokta hesabını yazdım; ölçüm gösterdi ki formül doğruymuş, gider farkıymış. Yazdığım kod
   ölçüldü, gereksiz bulundu ve silindi. Doğru gözlem + yanlış gerekçe = hata.
3. **Mutasyon testini eksik kurdum.** İlk regresyon testim, sabit nokta hesabı olmadan da
   geçiyordu (ölçüm: bu kurulumda iki sayı zaten aynı). Testi doktorun sayısını hook'un
   teslim ettiği boyutla karşılaştıracak şekilde yeniden kurdum; sonraki turda o da gereksiz
   çıktı (bkz. 2) ve testi gerçek sözleşmeye göre yeniden yazdım.
4. **Düzeltmeden önce ölçmedim.** `continuity_turn` koşulunun düştüğünü ve `claim_check`'in
   `SessionStart`'ta her zaman `True` döndüğünü, uyarıyı düzeltmeden önce okusaydım, iki hatalı
   çözümü (sabit nokta, ortak `opening_warning`) yazmam gerekmezdi. Kırmızı testlerin *ne
   söylediğine* bakmak yerine önce okumam gerekiyordu.
