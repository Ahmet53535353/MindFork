# Upstream Birleştirme 2 (merge upstream/main f9a8b5f → feat/explicit-memory-typing)

Tarih: 2026-09-25 · Dal: feat/explicit-memory-typing · Durum: ONAYLANDI
Önceki: `2026-09-25-upstream-merge-plan.md` (M1 = 3ceb8e9, aynı oyun kitabı).

## Bağlam

- Taban: M1 sonrası upstream tepe `f88fa59` (3.4.0). Upstream aynı gün +25 commit:
  `f9a8b5f`. Yarış hızı yüksek — M2 sonrası PR adımı önerilir.
- Bizim dal tepesi: `444c0c4` (passage tip kapıları dahil, 681/681).
- Tema kümeleri: reddedilen çıkarım olgunlaştırma (`rejected_at` ISO + gramer sabitleme,
  `validity.ignored_rejections` doctor bulgusu, `rejected_matches` + jev `previously_rejected`,
  kısa başlık limiti), görev sözleşmesi sertleştirme (kapanış update'inde criterion/opt-in
  kilidi + açıklamalı redler), bilgi tazeliği #109 (knowledge_freshness, V2 çakışma
  tespiti, Stop hatırlatması), doktor ölü bağlantı denetimi.

## Kuru deneme kanıtı (merge-tree, 2026-09-25)

- `git merge-tree --write-tree HEAD FETCH_HEAD` → ağaç `905319c`, **sıfır metin çakışması**.
- Çift-dokunuş dosyaları (otomatik birleşen, semantik denetim gereken 4 dosya):
  `beyin_v3.py`, `beyin_v3_sync.py`, `SKILL.md`, `PREFERENCES.md`.
- Birleşik ağaçta denetlenen sıcak noktalar:
  - `_eligible(audience, project, rejected_only=False)` — upstream'in yeni bayrağı geldi,
    tip kapılarımız (`resolve_type_filter`/`record_matches_types`) üzerinde aynen duruyor;
    `rejected_matches` yalnız `rejected_only=True` ile çağırıyor → etkileşim yok.
  - sync: "varsa geçerli" tip doğrulaması ve `allowed` kümesi birleşimi korundu.
  - SKILL.md tip tavsiye cümlemiz ve PREFERENCES.md tip kapısı maddemiz + upstream'in
    tazelik dokümanları birlikte duruyor.

## Adımlar

1. `docs/specs/2026-09-25-upstream-merge-2-plan.md` (bu dosya) → commit yok, merge ile gider.
2. `git merge FETCH_HEAD` (çakışma öngörülmüyor; olursa ilke: upstream refactor kazanır,
   bizim özellikler port edilir).
3. Tam paket `discover` yeşil (681 + upstream'in yeni testleri) → merge commit.
4. Push; fork `main` → `f9a8b5f` hızlı-ilerlet.
5. Record'a kilometre taşı + bu spec'e sonuç bölümü.

## Riskler

- Sessiz semantik: `rejected_matches` kapı paylaşımı ve task-sözleşmesi sertleştirmesi
  bizim sync birleşimimizle test düzeyinde doğrulanır (tam paket frenidir).
- Artan test paketi ilk koşuda bilinmeyen kırık üretebilir → merge commit öncesi tam yeşil.

## Uygulama sonucu

- Kuru deneme doğru çıktı: sıfır metin çakışması, `ort` stratejisi 4 çift-dokunuş dosyasını
  kendiliğinden birleştirdi; merge commit `a136a2a`.
- Tam paket: **725/725 yeşil** (681 + ~44 yeni upstream testi, skipped=1).
- Fork `main` → `f9a8b5f` hızlı-ilerletildi.
- Sonraki adım önerisi artık acil: PR (dal, upstream'in iki dalgasını da taşıyor).
