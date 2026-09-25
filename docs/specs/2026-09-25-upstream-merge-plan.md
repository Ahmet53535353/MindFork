# Upstream Birleştirme Planı (merge upstream/main → feat/explicit-memory-typing)

Tarih: 2026-09-25 · Dal: feat/explicit-memory-typing · Durum: ONAY BEKLİYOR

## Bağlam

- Tabanımız: release 3.3.0 (3868d11, avenoxai:main merge).
- Upstream (`avenoxai/avenoxbeyin` main) 23–24 Eylül'de ~61 commit aldı:
  fair-share pack_context (#79/#81), passage-level strict context (#83),
  companion hijyen limitleri + companion-compact (#96), task tamamlama
  sözleşmesi (#92), receipt kurtarma (#75), secret taraması genişletme (#76),
  OMP harness, jev düzeltmeleri.
- Bizim dal: 13 commit — bellek tipleri, FTS5/BM25, RRF + semantic kanca,
  otomatik tip sezgisi (yumuşak kapı), companion ends() bütçe dolumu,
  docs ve tests/custom.

## Çakışma analizi (upstream commit → bizim değişiklik → risk)

| Upstream değişikliği | Bizim değişiklik | Risk |
|---|---|---|
| `beyin_v3.py` `_eligible` refactor: görünürlük/güven/proje kapıları `_retrieve` döngüsünden taşındı (026007fe) | Aynı döngüye `types`/`type_gate` filtreleri eklendi | 🔴 neredeyse kesin |
| `beyin_v3.py` `pack_context` yeniden yazımı: ölçülmüş tabanlar, korumalı en iyi kaynak (b184a35, #79) | `pack_context` değişmedi; `_retrieve` dönüş hattı aynı bölgede | 🟡 orta |
| `beyin_v3.py` passage strict context yönlendirmesi (0ee0e43, #83) + `beyin_v3_passage.py` (yeni dosya, çakışmaz) | `_retrieve` sıralama bloğunda FTS/RRF | 🟡 orta |
| `beyin_v3_companion.py` hijyen satırı `context()` içine (#96) | Aynı fonksiyonda `ends()` dolum düzeltmesi | 🔴 yüksek |
| `beyin_v3_sync.py` secret/facts + receipt değişiklikleri (#76/#75) | VALID_MEMORY_TYPES sync doğrulaması (ilk oturum) | 🟡 orta |
| `tests/v3_task_create_test.py` (#92), `v3_secret_filter_test.py` (#76), companion bütçe testleri (#96) | Önceki oturumların aynı dosyalardaki test düzenlemeleri | 🔴 yüksek |
| `v3_semantic_test` holdout kapısı | Tip sezgimiz holdout sorgularını filtreleyebilir | 🟡 test düzeyi |

## Strateji: MERGE (rebase değil)

Gerekçe: 13 commit zaten GitHub'a push edildi. Rebase geçmişi yeniden yazar
(force-push zorunlu, paylaşılan dal bozulur) ve çakışmayı 13 ayrı committe
ayrı ayrı çözmeyi gerektirir. Merge mevcut geçmişi bozmaz, çakışmayı tek
noktada çözmez sağlar, iptali güvenlidir.

## Adımlar

1. **Fetch + kuru deneme:** upstream main fetch; `git merge-tree` ile kesin
   çakışma dosyası listesi çıkar → kullanıcıya raporla, merge öncesi onay al.
2. **Merge:** `git merge upstream/main`. Çözüm ilkesi: **upstream refactor
   kazanır, bizim özellikler üstüne port edilir** —
   `(a)` types/type_gate kapıları yeni `_eligible` akışına uyarlanır,
   `(b)` FTS/RRF sıralama bloğu yeni `_retrieve` yapısında korunur,
   `(c)` ends() dolum düzeltmesi hijyen satırıyla birleştirilir,
   `(d)` test dosyalarında iki tarafın testleri birleşim (union) olur.
3. **Tam test koşusu:** `python3 -m unittest discover tests -p "*test.py"`
   (upstream'in yeni testleri + 27 custom test dahil). Özel dikkat:
   `v3_companion_budget_test`, `v3_semantic_test` holdout, `v3_turkish_test`,
   `v3_fts5_test`, `v3_rrf_hybrid_test`, `v3_type_inference_test`.
4. **Yeşil → merge commit + push. Kırmızı → kök neden düzelt, 3'e dön.**
   Yeşilsiz commit yok.
5. **Fork main eşitleme:** Ahmet53535353/MindFork main → upstream'den
   fast-forward.
6. **(Ayrı karar) PR:** fork main'ine ve/veya upstream contribution
   (hibrit arama + tip sezgisi; #77 geçmişi katkıya açık).

## Riskler ve frenler

- Sessiz semantik çakışma (testlerin geçtiği ama davranışın bozulduğu
  bölge): `_eligible` portunda tip kapılarının gerçekten uygulandığını
  doğrulayan entegrasyon testi merge sonrasına bırakılmadan koşilir.
- Upstream test sayıları/artan paketi ilk koşuda bilinmeyen kırıklar
  üretebilir: merge commit'ten önce tam yeşil şartı bunun frenidir.
- `pack_context` taban sözleşmesi değişti (#79): custom bütçe testimizin
  `.95` eşiği upstream'in "best source share"ı ile gerileirse eşik
  yükseltilmez, ends() dolum davranışı yeniden ölçülür.
