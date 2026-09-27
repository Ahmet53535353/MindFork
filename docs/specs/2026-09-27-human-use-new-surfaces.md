# Yeni eklenen yüzeyler: ay kullanılmış vault'un elden geçirilmesi (2026-09-27)

Tarih: 2026-09-27 · Dal: feat/memory-consolidation · Durum: ONAYLANDI
Önceki: `2026-09-26-human-month-e2e.md` (1. tur, 14 soru), `2026-09-27-upstream-merge-4-plan.md`

## Amaç

İnsan kullanımı sınamasını **ikinci bir persona ile uzatmak** değil: mevcut sürücünün ürettiği
**bir aylık kullanılmış vault'u kalıcı olarak açıp**, upstream birleşimiyle ve bu dalda gelen
**yeni eklenen yüzeyleri gerçek komutlarla elden geçirmek.** Her gözlem üç yola gider:
kusur → kırmızı test + düzeltme; risk → SKILL/doctor kuralı; ölçülmüş davranış → kilitleyen test.

## Neden şimdi

1. tur 30 gün / **tek istemci** (`codex`) / **temiz kurulum** idi. O zamandan beri:

1. **Kart modeli** geldi (upstream #118) ve bağlam yoluna port edildi. Kartların
   birikmesi, 3000 karakter sınırı ve arşivleme **hiç ölçülmedi**.
2. **Günlük log varsayılan açık** oldu. 1. turda kapalıydı; açıkken oluşan yüzey ölçülmedi.
3. **Upstream yeni yüzeyler** getirdi: `state_location` (state kökü çözümlemesi), köprü ve
   companion belgeleri, Windows doctor fixture'ı.

## Vault tarifi (yeniden üretilebilir)

Sürücünün vault'u `tearDownClass`'ta silinir; ama `Month` (71) ve `run_month` (424) modül
seviyesindedir, bu yüzden **repo değişikliği olmadan** kalıcı vault materyalize edilir:

```python
import importlib.util
spec = importlib.util.spec_from_file_location(
    'month', '<repo>/tests/custom/v3_human_use_month_test.py')
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
m = mod.Month('/tmp/opencode/beyin-month')
mod.HumanMonthE2ETest.run_month(m)
```

Bu, **kurulu** vault + **kurulu** `beyin.py` + **kurulu** hook betiği + gerçek state veritabanı
olan, 12 oturum geçmiş, tatil haftası boş, ay sonu konsolidasyonu yapılmış, iki devir kartı
birikmiş bir vault verir. Aylık takvim sanaldır (2026-08-27 → 2026-09-25); ürün kodu gerçek
çalışır, sanal gün sonunda yalnız tarihler geri alınır.

Bu turda gözlemler **elden geçirme günlüğünde** tutulur; tur 1'de öğrenilen ders gereği
herhangi bir kalıcı dosya değişikliği testler tarafından yapılmaz.

## Denemeler

### A. Kart modeli (upstream #118 + `clip_cards` portu)

| # | Deneme | Komut | Aranan |
|---|---|---|---|
| A1 | Aynı gün ikinci oturum | kurulu hook betiği + yeni oturumun kartı | ilk kart dosyada sağ; `session_id[:8]` ayrışıyor |
| A2 | Kart dosyası 3000 karakteri geçiyor | gerçek kartlar ekle → `context` | hijyen uyarısı görünür; en yeni kart **bütün** |
| A3 | Arşivleme planı | `beyin.py companion-compact --dry-run` | plan makul; **hiçbir kart bölünmüyor**; dosyaya dokunmuyor |
| A4 | Arşivleme uygulaması | `beyin.py companion-compact` | `Arşiv/` altında dosya; `## Önceki oturumlar` işaretçisi **bağlama sızmıyor**; arşivlenen kart hâlâ aranabilir |

### B. Günlük log (varsayılan açık)

| # | Deneme | Komut | Aranan |
|---|---|---|---|
| B1 | Tek seferlik uyarı | ilk `SessionStart` çıktısı | uyarı **bir kez**, çalışan bir komut veriyor |
| B2 | Kapatma | `preferences --daily-log off` | uyarı tekrarlamıyor; profil değişikliği tercihi bozmuyor |
| B3 | Sır yüzeyi | gerçek anahtar + receipt + günlük log | süzgeç her yerde; **`daily/log/*.md` süzülmüyor**; SKILL kuralı yasaklıyor mu |

**B3 kararı (2026-09-27, onaylandı):** bulgu doğrulanırsa **ayrı iş kalemi** olarak birakılır;
bu turda yalnız ölçülür ve gerekçesiyle belgelenir. Nedeni: günlük logu ürün değil **ajan**
yazar, dolayısıyla ürün tarafında garanti verilebilecek tek şey süzgecin kapsamıdır; kalıcı
bir çözüm (kural + doctor uyarısı) kendi TDD turunu ister.

### C. Upstream'in yeni yüzeyleri

| # | Deneme | Komut | Aranan |
|---|---|---|---|
| C1 | State konumu | `doctor` → `state_location` | vault/state konumu, container içi mi |
| C2 | Taşınabilirlik | vault'u kardeş köke taşı → `doctor` + `context` | notlar, tercihler, companion kaynakları sağ |
| C3 | Çok istemci | `--harness claude` ile hook, aynı gün | oturum çakışması yok; kart kimliği ayrışıyor |

### D. İnsan yüzeyi (hiç ölçülmemiş)

| # | Deneme | Komut | Aranan |
|---|---|---|---|
| D1 | `recap` | `beyin.py recap --days 30` | kaynaklı özet; gün/limit sınırları |
| D2 | Ölçekte hatırlama | `context "geçen ay ne konuştuk"` | doğru kaynaklar; günlük log tur başı bağlamı şişirmiyor |

### E. Talimat ve komut yüzeyi

| # | Deneme | Komut | Aranan |
|---|---|---|---|
| E1 | **Komut denetimi (ilk kez)** | SKILL.md'deki her `beyin.py ...` | sözü verilen **her komut gerçekten var ve çalışıyor** |
| E2 | Ajan talimatı | kurulu `SKILL.md` + `CLAUDE.md` | kart kuralı ve "kart = devir, günlük log = kayıt" ayrımı metinde |

E1'in değeri: birim testleri tek bir komutu sınar, SKILL'in **tüm komut kümesini**
sınamaz. Bu sınıf hata (vaat edilen ama var olmayan komut) yalnız elden geçirmede çıkar.

## Uygulama sırası

1. kalıcı vault → sağlık denetimi (`doctor`, kart birikimi)
2. A → B → C → D → E sırasıyla, her deneme gözlem olarak kaydedilir
3. her kusur → önce kırmızı test, sonra düzeltme (B3 hariç)
4. hedefli testler → insan kullanımı sürücüsü 17/17 → tam paket, gerçek sayımlar
5. bu dosyanın sonuç bölümü: gözlem–karar tablosu

## Sonuç

Vault: `/tmp/opencode/beyin-month` (kurulu `beyin.py` + kurulu hook betiği + gerçek state),
30 sanal gün, 12 oturum, iki devir kartı, ay sonu konsolidasyonu yapılmış.

### Gözlem → karar

| # | Gözlem | Karar |
|---|---|---|
| A1 | Kart dosyası düzenlenince sonraki turda `Changed companion sources excluded` çıktı, kart düştü | **Yanlış alarm, kendi ortamım:** test izole ortamı `BEYIN_V3_NO_SPAWN=1` ile arka plan sync işçisini bilinçli kapatıyor ve sürücü bunu açık `sync` ile telafi ediyor. Gerçek ortamda (`SPAWN=1`) kart kaybolmadı. **Metot notu:** elden geçirme bu değişken olmadan yapılmalı |
| A1 | Aynı gün ikinci oturum, ikinci istemci | Kartlar bir arada kaldı, oturum kimlikleri ayrıştı. `[:8]` çakışması sadece sürücünün sahte kimliklerinde (`zeynep-g1`/`zeynep-g30` → `zeynep-g`); gerçek uuid'de sorun yok |
| A2 | 11 kart / 4095 karakter (sınır 3000) | Hijyen uyarısı bağlamın **ilk satırı** ve doğru komutu veriyor; bağlam en yeni **4 kartı bütün** veriyor; `[truncated: 7 older handoff cards not shown]` sayacı doğru (4+7=11). **Port gerçek vault'ta doğrulandı** |
| A3 | `companion-compact --dry-run` | Dosya SHA'sı değişmedi; 4 giriş / 1505 karakter planlandı; `deleted_chars: 0`, `model_calls: false` |
| A4 | Arşivleme uygulandı | Kartlar **birebir** taşındı (içerik kaybı yok), `## Önceki oturumlar` işaretçisi **bağlama sızmadı** (`excerpt` kesiyor), kalan dosya 2853 karakter |
| A4 | Arşivlenen kart aramada çıkmıyor | **Kusur değil:** arşiv kaydı `visibility: private` ile indeksleniyor (gizlilik sözleşmesi). Kilit kelime deneyi: `markdown_sources` kaydı var, metin indekste, ama arama özel kaydı döndürmüyor. Erişim yolu: işaretçi + dosyayı açmak |
| B1 | Günlük log uyarısı | Kurulum başına **bir kez**, yeni oturumda tekrarlamıyor (işaretçi `state/daily_log_notice`) |
| B2 | `preferences --daily-log off` | Uyarı sustu, log yazılmadı (blok sayısı 2→2), `economical` profili bağımsız tercihi **bozmadı** |
| B3 | Gerçek biçimli Stripe anahtarı | Süzgeç tüm ürün yollarında: receipt/state/knowledge/baglam/**recap** → 0 sızıntı, `[REDACTED]`. **Ama** günlük log ajan yazımı düz metin ve süzülmüyor; SKILL 162. satırda süzgeci yalnız receipt/note/task için sayıyor, log kuralında sır yasağı yok → **ayrı iş kalemi, düzeltilmedi** (onay gereği) |
| C1 | `doctor.state_location` | Pin var, buraya çözülüyor, uyarı yok, `sibling_state_roots: []` |
| C2 | Vault + state başka köke kopyalandı | Her komut `{"error":"ValueError","message":"runtime belongs to another vault"}` ile duruyor. **Belgelenmiş davranış** (`UPDATE.md:90`: veritabanı vault köküne bağlı, *state* taşımak `install_v3.py --state` ile desteklenir). Eksik olan eylem yönlendirmesi → **P3 öneri, uygulanmadı** |
| C3 | `--harness claude` aynı gün | Oturum açıldı, aynı kartlar geldi, `harness: claude` receipt'i kabul edildi; çakışma yok |
| D1 | `recap --days 30` | 13 kaynaklı kayıt, `from 2026-08-29 through 2026-09-27`, anahtar `[REDACTED]` olarak |
| D2 | `context "geçen ay ne konuştuk"` | 3 kayıt; **2'si `daily/log/`** — bu doğru: günlük log tam olarak "ne konuştuk" sorusunun kaynağı (strict yol dışlıyor, CLI yolu getiriyor) |
| E1 | `--help` ile dokümanlardaki komut denetimi | Sözü verilen **her** komut mevcut. İlk çıkarımda 3 "eksik" göründü, ikisi çıkarıcı hatasıydı (`--help` süslü parantez listesi kullanıyor), `recover` ise giriş betiğinin ikinci parser'ında → **kalıcı nöbetçi testi eklendi** |
| E2 | Kurulu `CLAUDE.md` tek satır | **Tasarım:** `install_v3.py:22` — Claude Code `AGENTS.md`'yi atladığı için `CLAUDE.md` `@AGENTS.md` ithalatçısı. Gerçek protokol kurulu `AGENTS.md`'de (45 satır), kart kuralı orada |

### Bulgu → düzeltme

**F-B (P1, gerçek kusur, düzeltildi): `clip_cards` dosya sırasına güveniyordu.**
Elden geçirmede üretildi ve gerçek vault'ta doğrulandı: en yeni kartı dosyanın **sonuna** ekleyen
ajan (eski tek-kart kuralının doğal hatası) kendi devir kartını kaybediyor, üstelik işaretçi
düşen kartlara *"older"* diyordu. Kök neden: kart listesi konumdan geliyordu.

Düzeltme: kartlar **kendi `## ` başlık tarihine** göre sıralanıyor (`stamp()` yeniden kullanıldı;
tarihsiz başlık en sona, kalanı yerinde). Kırmızı test önce yazıldı ve doğru nedenle kırmızıydı
(`HEAD_SONKART not found`), sonra yeşile döndü: `tests/v3_companion_multicard_test.py` 9/9.
Düzeltme kurulu vault'a kopyalanıp gerçek dosyada doğrulandı: sona eklenen kart artık ilk sırada,
işaretçi gerçekten eski kartları sayıyor.

### Eklenen kalıcı nöbetçi

`tests/v3_promised_commands_test.py` (3 test, 6 alt test): talimat dosyalarındaki her
`beyin.py <fiş>` gerçekten kayıtlı mı. Kayıt iki katmandan geliyor: `scripts/beyin_v3.py`
parser'ı + `scripts/beyin_entry.py`'nin önceki yakaladığı fişler (`update`, `rollback`, `recover`).
Bu sınıf hata (vaat edilen ama var olmayan komut) birim testlerin göremediği yerdir; ilk
elden geçirmede ölçüldü ve temiz çıktı.

### Doğrulama

- `tests/custom/v3_human_use_month_test.py`: **17/17**
- tam paket: **925 passed, 1 skipped, 2295 subtests** — 0 kırmızı (birleşim sonrası 920 idi;
  artış 2 çok-kart testi + 3 komut nöbetçisi testi)

### Kalan işler

1. **B3 (ayrı iş kalemi, onay gereği):** günlük log sır yüzeyi. Seçenekler: (a) SKILL kuralı —
   Özet'e anahtar/özel içerik yazma; (b) `doctor` uyarısı; (c) ürün tarafında `daily/log/` okunurken
   süzgeç. (c) kalıcı çözümün tek yolu, kendi TDD turu ister.
2. **P3 öneri (uygulanmadı):** `beyin_v3.py:227/256` `runtime belongs to another vault` hatası
   eylem yönlendirmiyor. Vault taşıma desteklenmiyor; mesaj `install_v3.py --state` yolunu
   ve "vault kökü bağlıdır" gerçeğini söylemeli.
3. `tests/v3_human_use_month_test.py` sürücüsünde `s1[:8]`/`s30[:8]` aynı sekiz karakteri veriyor
   (`zeynep-g`); gerçek kimliklerde sorun yok ama sürücü kartları ayırt edilemez kılıyor.
4. Kart dosyası sınırı (3000) paralel oturumlarda birikince uyarı çıkar ve `companion-compact`
   arşivler; bu upstream'in tasarımı, bizim ek ölçüm değil.
