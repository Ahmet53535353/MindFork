# Upstream Birleştirme 5 (merge upstream/main da36d8c) + saat kırılganlığı düzeltmesi

Tarih: 2026-09-28 · Durum: TAMAMLANDI · İlgili: `2026-09-27-upstream-merge-4-plan.md`,
`2026-09-27-human-use-new-surfaces.md`, `2026-09-28-test-clock-fragility.md`

## Bağlam

İki ayrı iş, aynı gün:

1. **Wiki geri alındı.** 16 commitlik `docs/wiki/` işi (tasarım + plan + 12 sayfa + 2 test
   dosyası + kök `README.md` bağlantısı) kullanıcı kararıyla kaldırıldı. Dal
   `8b8a3fa`'ya geri alındı ve `push --force-with-lease` ile uzağa yansıtıldı.
2. **Yeni upstream dalgası:** `eed645c → da36d8c`, 15 commit, aralarında **3.5.0 ve 3.5.1**
   olmak üzere iki sürüm.

## Saat kırılganlığı (birleştirmeden önce, ayrı commit `a4ecf76`)

Wiki push edildikten sonra tam paket yeşil değildi: iki test kırmızıydı ve ikisi de aynı
iddiada — `archive/auto-dream/<gün>/report.md` beklenen yolda değil, ama `wrote` doğru. Yani
pencere çalışmış, rapor başka bir güne yazılmıştı.

Kök neden **saat dilimi**: ürün pencere gününü UTC ile kuruyor (`beyin_v3_dream.py:62` `_now()`,
`:737` `day = manifest['window']`), testler `dt.date.today()` ile yerel günü hesaplıyordu.
UTC+3'te yerel gece yarısı ile UTC gece yarısı arasında günler bir gün ayrışır; 2026-09-28
yerel gece yarısında başladığı için paket düştü, UTC de 28'e geçince yeşile döndü — yani testler
**her gün üç saatlik bir kırılma penceresindeydi**.

Düzeltme iki parça:

- **İddialar tarihi yeniden hesaplamıyor**, ürünün bildirdiği `report_path` yolunu kullanıyor
  (`dream --apply` `report_path` döndürüyor, `beyin_v3_dream.py:753`).
- **`tests/conftest.py`** tüm paketi UTC'ye sabitliyor; `isolated_env()` de alt süreçlere
  `'TZ': 'UTC'` veriyor. `v3_dream_phase2_test.py`'deki sabit fixture'lar (`self.today =
  '2026-09-26'`) bilerek değiştirilmedi — dosyanın geri kalanı deterministik olmaya ona bağlı.

Kanıt: `TZ=Etc/GMT+12` altında (yerel 2026-09-27, UTC 2026-09-28) iki test **önceden düşüyordu**,
düzeltmeden sonra geçiyor. Aynı koşul wiki öncesi noktada (`5cc5cab`) da düşüyordu; yani bulgu bu
dalın işi değil, saatin işiydi.

## Kuru deneme (merge-tree, 2026-09-28)

`git merge-tree --write-tree HEAD upstream/main` → ağaç `cb1f5cc`, **tek içerik çakışması:
`tests/v3_package_helpers.py`**.

Upstream'in 15 commitinin dokunduğu 15 dosyanın üçü bizimle kesişti ve **kendiliğinden
birleşti**: `README.md`, `scripts/beyin_v3.py`, `docs/v3/UPDATE.md`.

### Tek çakışmanın niteliği

İki taraf **aynı `isolated_env` sözlüğünü** değiştirmiş, iki tarafın da amacı farklı ve ikisi de
geçerli:

- **upstream** (`00a48b2`): `SYSTEMROOT`/`WINDIR` korumasını satır içi döngüden
  `windows_runtime_env()` yardımcısına taşıdı (Python 3.14 + OpenSSL 3.5'te `ssl.SSLContext()`
  bu değişkenler olmadan düşüyor).
- **biz** (`a4ecf76`): sözlüğe `'TZ': 'UTC'` ekledik.

Çözüm ilkesi M3/M4 ile aynı: **upstream'in refactor'ı kazanır, bizim eklememiz ona port edilir.**

```python
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'utf-8', 'BEYIN_V3_NO_SPAWN': '1',
           # The product dates windows in UTC; a local-time subprocess reads a different day for
           # three hours a day. Pinned here as well as in tests/conftest.py because callers build
           # their own env from this dict and would otherwise inherit the developer's timezone.
           'TZ': 'UTC'}
    env.update(windows_runtime_env())
```

Bu tahmini değil ölçümlüydü: dalı düşüren iki testi, wiki öncesi noktada yeniden koşturup aynı
şekilde düştüklerini göstermek, saat teşhisini doğrulamıştı.

## Birleşim sonrası anlamsal denetim

`scripts/beyin_v3.py` iki tarafın da değişikliklerini taşıyor:

- bizim: `exclusion_notice` (5), `beyin_v3_exclusions` (2)
- upstream'in: `_in_package_container` (5), `state_location` (3), `releases` (4),
  `beyin_v3_releases` (2)

Günlük log bağlantısı sağlam: `beyin_v3.py`'de `SessionLog` diye bir fiş yok, bağlantı
`template/.claude/scripts/beyin_v3_hook.py:338-344` üzerinden `beyin_v3_sessionlog`'ı içe
aktarıyor; `--daily-log` tercihi `beyin_v3.py:399`'da duruyor.

Sürüm: depoya yeni **`VERSION`** dosyası geldi (`3.5.1`). Bu, sürümün nerede sabitlendiğini
değiştiriyor — `template/.beyin-version` hâlâ `2.3.0` (bayat, dokunulmadı).

## Doğrulama

- Tam paket: **929 passed, 1 skipped, 2302 subtests** — 0 kırmızı, 11 dk 24 sn.
  (Saat düzeltmesinden sonra, birleştirmeden önce: 925 passed / 1 skipped.)
- Upstream'in güncellediği 4 test dosyası tek tek: 68 passed.
- `TZ=Etc/GMT+12` altında `tests/custom/v3_dream_phase2_test.py`: 21 passed.

## Push ve refspec notu

`git push --force-with-lease` iki kez "stale info" ile reddedildi: `remote.origin.fetch`
refspec'i **tek dala daraltılmış** (`+refs/heads/feat/explicit-memory-typing:...`), yani bu dalın
izleme referansı hiç oluşmadı ve lease'in karşılaştıracağı taban yoktu. Çözüm: uzak tepe
`856273e`'ydi ve kimse bir şey itmemişti; açık beklenen değerli biçim kullanıldı
(`--force-with-lease=feat/memory-consolidation:856273e…`). Kaldırma gerçekten geri sarmaydı:
`8b8a3fa`, `856273e`'nin atasıydı.

**Kalan iş kalemi (bu dalın konusu değil):** `remote.origin.fetch` refspec'i genişletilmeli;
aksi halde bu dal için `git fetch origin` hiçbir izleme referansı tazelemiyor ve
`--force-with-lease` her seferinde reddediliyor.

## Kalan işler

1. `remote.origin.fetch` refspec'i (yukarıda).
2. `template/.beyin-version` bayat (`2.3.0`) — artık kök `VERSION` var, bu dosyanın ne olduğu
   belirsiz; ayrı iş kalemi.
3. Günlük log ile konsolidasyon arasındaki gün anlayışı farkı: `beyin_v3_sessionlog.py` yerel
   tarih kullanıyor, `beyin_v3_dream.py` UTC. `TZ=UTC` testleri güvenli kılıyor ama ürünün
   kendisinde iki anlayış duruyor.
4. `test_receipts_inside_window_are_referenced` tek başına geçiyor, tam pakette düşüyor — sıra
   bağımlılığı, ayrı iş kalemi.
