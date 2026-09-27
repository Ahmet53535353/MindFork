# Upstream Birleştirme 3 (merge upstream/main db1f23d → feat/memory-consolidation)

Tarih: 2026-09-26 · Dal: feat/memory-consolidation · Durum: ONAYLANDI
Önceki: `2026-09-25-upstream-merge-2-plan.md` (M2 = f9a8b5f, aynı oyun kitabı).

## Bağlam

- Taban: M2 sonrası upstream tepe `f9a8b5f` (3.4.0). Upstream 14 commit ilerlemiş:
  `db1f23d`, 16 dosya, üç dalga.
- Bizim dal tepesi: `5ff3ca5` (bir aylık insan kullanımı E2E'si ve takip
  düzeltmeleri dahil, 806/806 yeşil). `f9a8b5f..HEAD` = 60 dosya, +5926 satır.
- Upstream dalgaları:
  1. **Bileşen/skill hariç tutma** (#108, #94 item 7): yeni
     `template/.claude/scripts/beyin_v3_exclusions.py`, `.beyin-exclusions.json`,
     `--exclude-component`/`--include-component`, install/update/doctor
     entegrasyonu, `tests/v3_component_exclusion_test.py`. Upstream'in kendi
     notundan: `excluded_components` tercih şemasından **çıkarıldı**, 3.4.0'a
     rollback güvenliği için ayrı dosyaya taşındı.
  2. **Kaynaklı yakın dönem özeti** (`recap`, #111): yeni CLI komutu,
     `beyin_v3_projections.py` içinde `_hidden_ref_sources`, `tests/v3_recap_test.py`.
  3. **state kökü çözümleme/sabitleme** (#113/#114): `scripts/beyin_entry.py` ve
     `install_v3.py`, `tests/v3_transaction_root_test.py`.

## Kuru deneme kanıtı (merge-tree, 2026-09-26)

`git merge-tree --write-tree HEAD upstream/main` → ağaç `2dadd6c`, **tek içerik
çakışması: `scripts/beyin_v3.py`**.

Çift-dokunuşlu 7 dosyadan 6'sı kendiliğinden birleşti (metinsel denetim gerekir):
`README.md`, `docs/v3/PREFERENCES.md`, `docs/v3/RUNTIME.md`,
`scripts/install_v3.py`, `template/.agents/skills/beyin/SKILL.md`,
`template/.claude/scripts/beyin_v3_projections.py`,
`template/.claude/scripts/beyin_v3_update.py`.

### Tek çakışmanın niteliği

Çakışma `preferences` alt komutunun gövdesinde: iki taraf da ayna bloğa
**bağımsız** bir özellik eklemiş.

- biz: `if args.daily_log is not None: changes['daily_log'] = args.daily_log == 'on'`
- upstream: `import beyin_v3_exclusions`, hariç tutma doğrulaması/kaydı ve
  `exclusion_notice`

Çözüm: **ikisi de tutulur.** Sadece "upstream kazanır" burada yanlış olur —
çakışmanın hemen dışındaki 287. satır (kendiliğinden birleşti)
`result['excluded_components'] = result_excluded` diyor; upstream bloğu
atlanırsa `NameError`. Bizim `daily_log` bloğu da günlük log özelliğinin ta
kendisi. İlke: *upstream refactor kazanır, bizim özelliklerimiz port edilir* —
iki tarafın özelliği de özellik olduğu için ikisi korunur.

### Denetimde doğrulanan iki şey

1. **Paketleme kendiliğinden çözülüyor.** `install_v3.py:RUNTIME_MODULES()` bir
   glob kullanıyor (`sorted(directory.glob('beyin_v3*.py')) + [_portalock.py]`),
   yani upstream'in yeni `beyin_v3_exclusions.py` modülü manifest'e **otomatık**
   giriyor; `beyin_v3_update.py` allowlist regex'i
   (`beyin_v3(?:_[a-z]+)*\.py`) de onu kapsıyor. Bu, `5f68006`'daki
   (tek kaynaklı modül listesi) düzeltmenin bu dalgayı bedava karşıladığı anlamına
   geliyor; o olmasaydı yeni modül yalnız gerçek vault'ta patlardı.
2. **Talimat/doküman birleşmesi tutarlı.** SKILL.md'de bizim `--daily-log`
   satırımız ve upstream'in exclusion satırları birlikte duruyor;
   `PREFERENCES.md` birleşiminde "varsayılan kapalı" gibi bizim yeni varsayılanımızla
   çelişen bir ifade kalmadı.

## Adımlar

1. Bu spec → merge commit ile gider.
2. `git merge -c core.merge.conflictstyle=diff3 upstream/main`; tek çakışma iki
   blokla çözülür.
3. Anlamsal denetim: 6 otomatik-birleşen çift-dokunuşlu dosya (aşağıdaki riskler).
4. Tam paket `discover` yeşil (806 + upstream'in üç yeni test dosyası) → merge commit.
5. Push; fork `main`'i hızla ilerlet.
6. Sonuç bölümü + record'a kilometre taşı.

## Riskler

- **Kurulum akışı iki tarafta da değişti.** Upstream state kökü sabitleme (#113) ve
  AGENTS.md byte-geri yazma düzeltmelerini, biz de `5f68006`'da manifest/portalock
  düzeltmesini ekledik. Aynı akışta iki değişiklik → `v3_releases_test`,
  `v3_component_exclusion_test`, `v3_transaction_root_test` yeşil olmadan merge
  commit atılmaz.
- **Tercih şeması.** Upstream `excluded_components`'ı `.beyin-preferences.json`'dan
  çıkardı. Bizim `preferences.validate()` bilinmeyen anahtarı reddediyor; bayat bir
  fixture veya test bu yüzden kırılabilir.
- **Belgelenmiş semantik sessizlik.** Metinsel birleşme doğru çıksa bile iki
  özelliğin aynı kod yolunda birleşmesi beklenmedik bir davranış verebilir; tam
  paket tek başına yakalamaz, 5. adımdaki denetim de yapılır.
- **Büyüyen paket.** Üç yeni upstream test dosyası ilk koşuda bilinmeyen kırık
  üretebilir (önceki spec'te de yazılı risk).

## Uygulama sonucu

_(merge sonrası doldurulur)_
