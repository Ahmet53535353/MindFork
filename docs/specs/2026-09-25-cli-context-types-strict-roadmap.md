# Roadmap: CLI `context` için `--types` / `--strict` bayrakları

- **Durum:** KARARA BAĞLANDI, UYGULANMADI (2026-09-25 canlı vault E2E bulgusu #1)
- **Öncelik:** düşük-orta (production akışını etkilemez; yetenek/hata-ayıklama konforu)
- **Tahmini iş:** ~30-45 dk, tek commit

## Sorun

Çatala özel iki retrieval özelliği store API'de tam çalışıyor ama kök CLI `context`
yüzeyinden ulaşılamıyor:

1. `context_for(..., types=[...])` — açık tip filtresi (`resolve_type_filter` politikası).
2. `context_for(..., strict=True)` — passage yolunun disipline enjekte davranışı; hook
   production'da kendisi `strict=True` geçiyor (`beyin_v3_hook.py:393`).

Kök CLI `scripts/beyin_v3.py` params beyaz listesi yalnız `query/project/audience/
statuses/limit/budget_chars` kabul ediyor; `--file` JSON'una `types` yazmak
`"Context JSON contains unsupported fields"` hatası veriyor.

## Kazanç

- **Aynı-kaynak hata ayıklama (`--strict`):** "hook yanlış enjekte etti" şüphesinde
  kullanıcı/agent hook'un gördüğü passage-çıktısını CLI'dan birebir üretebilir; bugün
  CLI her zaman note-level yolu koşuyor, çıktısı hook'un çıktısı değil.
- **Agent yeteneği (`--types`):** hook'suz terminalde ipucu içermeyen sorguda bile
  ("fatih durum") bilinçli bellek türü seçilebilir. Yazma tarafını SKILL.md öğretiyor;
  okuma tarafı CLI'da görünmez — semetri tamamlanır.

## Tasarım kararları

- `--types` → `action="append"`, **argparse `choices` YOK**: geçerlilik tek kaynakta
  (`resolve_type_filter`) kalsın; geçersiz değer CLI'da `invalid memory type: ...`
  ValueError mesajıyla görünür (bugünkü davranışla birebir aynı).
- `--strict` → `store_true`.
- Params sözlüğüne iki anahtar **her zaman** eklenir (`"types": args.types` (vars. `None`),
  `"strict": args.strict` (vars. `False`)) — böylece `--file` JSON beyaz listesi de
  otomatik açılır. Zararsız: `types=None` resolve'un infer dalına düşer, `strict=False`
  note-level yolda zaten varsayılan; `retrieve`/`shared_context` kwargs'ları imza
  düzeyinde kabul ediyor (kontrol edildi: `beyin_v3.py:493`, `:918`).
- SKILL.md `context` bölümüne tek cümlelik kullanım notu.

## Kabul testleri (taslak hazır — bu spec'in ekidir)

`tests/custom/v3_cli_context_flags_test.py` olarak, mevcut doctor-subprocess kalıbıyla:

1. `--types episodic` → yalnız episodic id; `--types semantic` → yalnız semantic id.
2. `--types mavi` → rc != 0 + `invalid memory type` mesajı.
3. `--file` JSON `{"types":["episodic"]}` → filtre uygulanır.
4. `--strict` passage disiplisini taşır: taban-altı bütçede note-level record döndürürken
   strict yolu `abstained=True` + boş records döndürür; geniş bütçede record geri gelir.

Fixture: iki tipli not (`episodic`/`semantic`), tek proje; CLI `context` yazmasız
okuma için `--no-sync` yerine normal akış (sync idempotent).

## Kapsam dışı

- Hook'a types geçirmek (bilinçli: hook ipucu-sezimiyle çalışıyor; override API'de).
- Başka alt-komutlara types eklemek (`jev-*` advisory yolları ayrı karar).

## Uygulama sırası

1. Yukarıdaki test dosyasını yaz → **kırmızı** olmalı (argparse "unrecognized arguments").
2. `scripts/beyin_v3.py`: iki `add_argument` + params anahtarları.
3. Hedefli test yeşil → tam paket → SKILL.md cümlesi → commit + push.
4. Bu spec'in durumunu `TAMAMLANDI` çevir, record'a kilometre taşı ekle.
