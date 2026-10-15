---
name: beyin-upstream-merge
description: Upstream'den gelen commit'leri bu fork'a merge et, kendi düzeltmelerimizi
  koruyarak. Upstream geride kaldığında veya Ahmet "upstream'i al / merge et / yeni sürüm
  var mı" derse kullan.
---

# Upstream merge

Bu repo bir fork'tur (`Ahmet53535353/MindFork`), upstream'i `avenoxai/avenoxbeyin`.
Merge'in işi **upstream'in commit'lerini almak ve bizim düzeltmelerimizi korumaktır**.
Upstream `push` yetkisi olmayan bir bakımcının deposudur (`pull`); buradan PR gönderilmez,
yani upstream'in bize ne verdiği tek yönlü akar.

Yalnız Ahmet çağırdığında çalışır. Upstream ilerlediğinde kendiliğinden başlama.

## Asıl risk: sessiz düşme

Merge çakıştığında git iki tarafı birleştirmeyi dener ve **çözülmüş görünür**. Yanlış
çözümle geçen bir değişikliği test paketi yakalamayabilir. 2026-09-26'da `PROJECTION_GUARD`
bir merge'de kayboldu; ancak onu kapsayan test ancak 2026-10-10'da yazıldı, yani **14 gün**
boyunca korumasızdı. Yakalayan şey test değil, AST taramasıydı.

Bu yüzden bu akış iki şeyi ayrı tutar: **testler davranışı**, **anlamsal denetim yapıyı**
korur. Testlerin yeşil olması tek başına "merge doğru" demek değildir.

---

## Adım 0 — Ön koşul: refspec

`remote.<ad>.fetch` bütün dalları izlemeli. Tek dal izleyen bir refspec, `origin/main`'i
bayatlatır ve `--force-with-lease` her push'ta "stale info" ile reddeder; yerel ref ile
sunucu sessizce ayrışır (ölçülmüş örnek: yerel `f9a8b5f`, uzak `db1f23d`).

```sh
python3 .agents/skills/beyin-upstream-merge/measure_merge.py --only preflight
```

`KISITLI` çıkarsa **push'a geçme**, önce `git config --add remote.<ad>.fetch
'+refs/heads/*:refs/remotes/<ad>/*'` ile düzelt.

## Adım 1 — Ölç, tahmin etme

```sh
python3 .agents/skills/beyin-upstream-merge/measure_merge.py --only merge
```

Çakışma listesini **elle sayma**. 2026-09-27'de taban satırlarına bakarak 5 çakışma
tahmin edildi; `merge-tree` **1** dedi. Bu betik aynı hesabı yapar ve hunk sayısını
sonuç ağacındaki blob'tan okur (insan-okunur merge-tree çıktısı tüm dosyaların diff'ini
birleştirir; oradan saymak her dosyanın hunk'ını toplam verir).

`behind 0` çıkarsa iş yoktur, burada dur.

## Adım 2 — Taban: merge'den önce tam paket

```sh
python3 -m pytest tests/ -q -p no:cacheprovider
```

Sayıyı **yaz**. Sonra patlayan test merge'in mi tabanın mı suçlu, ancak bu sayıyla
ayrılabilir. Bunu atlamak "yeşil testler işe yaradı" yanılgısının en pahalı yoludur.

## Adım 3 — Kapsama: hangi düzeltmemiz testsiz

```sh
python3 .agents/skills/beyin-upstream-merge/measure_merge.py --only coverage
```

`divergences.md` her yerel düzeltmeyi bir **davranış işareti**yle listeler; betik her
işareti `tests/` altında arar. `YOK` çıkan düzeltme merge'de sessizce düşebilir: ya test
yaz, ya da Ahmet'e "bu düzeltme korumasız, düşerse ne olur?" diye sor.

**Sembol adıyla kapsama ölçme.** 2026-10-15'te `VALID_MEMORY_TYPES` için grep sıfır test
dedi ve boşluk sanıldı; tip kapısının davranışı 4 test dosyasında kapsanıyordu.

## Adım 4 — Merge

```sh
git merge --no-commit --no-ff upstream/main
```

Rebase değil, merge. 2026-09-25'te bilinçle seçildi: rebase 290 commit'in SHA'sını
değiştirir, paylaşılan dalları bozar ve geri dönüşü zorlaştırır. `--no-commit` testler
koşulana kadar çalışma ağacının taşınmaması içindir.

## Adım 5 — Çakışma çözümü

### 5a. Mekanik: iki taraf da durabiliyorsa birleştir

İki tarafın değişikliği birbirinin yerine geçmiyorsa — import listeleri, fonksiyon
imzaları, birbiriyle ilgisiz iki özellik — ikisini de tut. 2026-10-15'te 4 çakışmanın
3'ü bu tiptendi.

Bunun testi sorulabilir: **çözümden sonra iki tarafın da ne yaptığı hâlâ dosyada mı?**

### 5b. Anlamsal: DUR, ölç, kırmızı test önce, sonra sor

İki taraf **aynı karar yüzeyinde** değişiklik yapıyorsa (öncelik payı, eşik, politika),
bu mekanik değildir. Rastgele birleştirme sessiz bozulmadır.

Sıra şu:

1. **Dur.** Tahmin etme, "`union` yeter" deme.
2. **Ölç.** Her seçeneğin neyi bozduğunu say. 2026-10-15'te `FLOORS` için altı aday
   tablo tarandı; ölçüm şunu gösterdi:

   | tablo | Tetikleyici (gerçek vault, 4750) | bütçe testi (2000) |
   |---|---|---|
   | upstream'ın tablosu, Tetikleyici paysız | **0 karakter** | GEÇER |
   | + `Tetikleyici.md: .15` | bütün | **KIRIK** |
   | Kurallar .45 + Threads .10 | **bütün** | **GEÇER** |

   Ölçüm yapmadan seçenek sunmak, seçimi gerekçeden çıkarır.
3. **Kırmızı test önce.** Çözüm bir davranış değişikliği getiriyorsa, testi önce yaz ve
   **kırmızı olduğunu gör** (2026-09-27'de R1–R6 böyle yazıldı).
4. **Sor.** Ölçüm tablosuyla birlikte, tek soruda seçenekleri ver. Uygulama cevabından
   sonra.

### Asla yapma

- İki tarafı da sessizce atmak. Bir tarafı koruyamıyorsan sor.
- Test kırıldığında "test yanlış" demek. Önce **testin mi ürünün mü** yanlış olduğunu
  kanıtla. 2026-10-15'te bir test fazla spesifik bir sözleşmeydi (`{}` beklerken upstream
  artık uyarı da basıyordu) ve düzeltildi; ama aynı gün başka bir kırık **gerçek bir
  hataydı** (`type` izin kümesine eklenmemişti) ve yalnız kanıtlayınca görüldü.
- Merge'in sessizce kaldırdığı bir sembolü fark etmemek. Adım 3'ün raporu bunun için var.

## Adım 6 — Birleşim sonrası anlamsal denetim

Testler yeşil olsa da **mimari değişmiş olabilir**. Bu adım testlerin göremediğini arar:

1. Her çakışan dosya için iki tarafın ne kattığını tek tek say. 2026-09-28'de
   `scripts/beyin_v3.py` için bizim `exclusion_notice` (5 satır) ve upstream'in
   `_in_package_container` (5) bulundu; ikisi de duruyordu.
2. **Bağlantıları izle.** Upstream bir bağlantıyı başka yere taşımış olabilir. Aynı
   gün `SessionLog` diye bir fiş yoktu; bağlantı `beyin_v3_hook.py:338-344` üzerinden
   `beyin_v3_sessionlog`'a gidiyordu. Sembol yok diye bağlantı da yok sanma.
3. **Kaynak değişti mi?** Aynı gün upstream `VERSION` dosyasını getirdi ve sürümün
   nerede sabitlendiği değişti. Yayın adımı bu yüzden `VERSION`'u okumak zorunda.

Bu adımın bulgusu olmasa da yapılır; yoksa "yeşil testler = doğru merge" yanılgısıyla
kalır.

## Adım 7 — Doğrulama

```sh
python3 -m pytest tests/ -q -p no:cacheprovider     # tabanla karşılaştır
python3 scripts/evaluate_v3.py                      # CI'ın koştuğu ikinci kapı
python3 .agents/skills/beyin-upstream-merge/measure_merge.py --only coverage
```

Ayrıca **kapsam dışı bırakılanlar** listesini yaz: gördüğün ama çözmediğin kusur. Sessizce
geçmek, sonraki merge'de aynı yerde bir daha karşılaşmak demek.

## Adım 8 — Kaydet

1. `git add -A && git commit` — gövde **ne ölçüldüyse** onu yaz: çakışma sayısı, taban ve
   sonuç test sayıları, hangi karar senin onayınla alındı, hangi kapsam dışı bırakıldı.
2. `git push origin <branch>`
3. `docs/specs/YYYY-MM-DD-upstream-merge-N.md` — gelenek (11 merge, 7 not). İskelet:
   Bağlam · Kuru deneme · Çakışma niteliği · Adımlar · Riskler · Anlamsal denetim ·
   Doğrulama · Kapsam dışı · Süreçte bulunan kendi hataların
4. `python3 beyin.py receipt --harness <istemci> ...` (vault kökünden) ve `sync`
5. Merge notunda **kendi hatalarını** da yaz. 2026-09-27'de iki tanesi kayıtlıydı ve
   ikisi de sonraki dalgaların usulünü değiştirdi.

## Adım 9 — Yayın: DUR, ayrı onay iste

Buraya kadar **push dahil** skill'in işidir. Sonrası Ahmet'in açık onayına bağlı:

- Sürüm kaynağını oku (`VERSION` dosyası var mı, başka yere mi taşınmış)
- `VERSION`'ı artır: **özellik varsa küçük sürüm** (3.11.1 → 3.12.0), yalnız damga varsa
  yama sürümü. Updater aynı sürüm altında içerik değişikliğini uygulamaz
  (`update.py` noop döner) — bu yüzden damga yetmez.
- `python3 scripts/build_v3_release.py --output <ad> --version <sürüm>`
- **Varlık adı `beyin-v3-<sürüm>.zip` olmalı** (tire ile; `beyin-v3.<sürüm>.zip` değil).
  `beyin_v3_releases.py:102` bunu tam adıyla arar; yanlış ad `missing_package` verir.
  Yanlış yüklediysen release'i sil ve yeniden yükle.
- `gh release create v<sürüm> <zip> <zip>.sha256 --repo Ahmet53535353/MindFork ...`
- `python3 beyin.py update --check` → sonra `update`
- **GitHub `latest` ucu yeni release'i birkaç saniye geç gösterir.** İlk deneme
  `missing_package` verebilir; bu yarış koşuludur, paket adı hatası değildir. Yeniden dene.
- Vault'u güncelle, `doctor`'ı oku, receipt gönder.

Bu adım aynı zamanda **bedelini de hatırlat**: updater yalnız bu fork'a bakar. Upstream
yeni sürüm çıkarırsa görünmez; fork'a yüklenmeli ya da `beyin.py update --package <dosya>`
ile elle kurulmalı.

## Bilinen tuzaklar

| Tuzak | Belirti |
|---|---|
| Refspec tek dal izliyor | `--force-with-lease` "stale info"; yerel ref bayat |
| Varlık adı yanlış | `missing_package` (gerçekten ad yanlışsa) |
| `latest` ucu gecikir | `missing_package` birkaç saniye sonra düzelir — iki farklı hata |
| Çakışmayı elle saymak | Sezgi çürütülmüş bir dalga var; `merge-tree` esas |
| Sembolle kapsama ölçmek | Var diye "korumasız" sanmak; davranış kapsanmış olabilir |
| Yeşil test = doğru merge | Anlamsal denetim olmadan kalan yapısal kayıplar |