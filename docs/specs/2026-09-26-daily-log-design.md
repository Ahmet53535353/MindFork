# Günlük Oturum Logu (`daily/log/`) — model'siz B1

- **Durum:** ONAYLANDI, uygulama başlıyor (2026-09-26)
- **Kapsam:** opt-in, varsayılan kapalı; Last-Session semantiğine dokunulmaz

## Problem

- Kurucu tez (`docs/beyin-v2.md:20`): *"memory must be a mechanism, not a discipline."*
- V2 `flush.py` bunu model'li oturum-sonu özetiyle karşılıyordu; V3 model çağrısı
  sınırını korurken mekanizmayı da kesti. V3'te oturum izi üçe bölünmüş ve hepsi
  voluntarist: `Last-Session.md` tek-kerelik devir kartıdır (ajan yeniden yazarken
  önceki kaydını siliyor — kurucunun canlı şikayeti), `daily/v3/{gün}.md` yalnız
  **receipt vermiş** oturumları gösterir, `receipt` hiç otomatik değildir (bilinçli).
- Sonuç: receipt'siz ya da kötü yazılmış oturum iz bırakmaz → yazma tarafı kurur,
  çatalın okuma yığını (tipli hafıza, BM25, tip kapıları) okuyacak malzeme bulamaz.

## Tasarım — kayıt mekanizma, yorum disiplin

| Katman | Sahip | İçerik |
|---|---|---|
| Olgu bloğu | **hook (mekanizma)** | saat aralığı, harness, proje, prompt sayısı, oturum içi receipt referansları, reflection işareti — deterministik, her oturumda garanti |
| `### Özet` | **oturumdaki ajan (disiplin)** | V2 `flush.py` promptunun beş bölüm şeması: Bağlam / Önemli Konuşmalar / Alınan Kararlar / Öğrenilenler / Yapılacaklar + süzme kuralları ("karar, tercih, sonuç, açık iş kalır; araç çağrısı, tekrar, geçici ayrıntı çıkar"). Ek model çağrısı YOK; kalıcı değer yoksa boş bırakılır |

### Dosya ve blok

- Yol: `daily/log/YYYY-MM-DD.md` (projeksiyonların `daily/v3/{gün}.md`'siyle çakışmaz;
  `render()` kalıbı aynı: atomic tmp+rename).
- Frontmatter: `{"kind":"note","type":"episodic","visibility":"internal"}` —
  `type` ZORUNLU: açık `--types episodic` filtresi tip-None kaydı dışlar; tiplenmemiş
  log kendi tip sistemimizden men edilmiş olurdu.
- Blok biçimi (SessionStart'ta açılır, SessionEnd'de tamamlanır):

```markdown
<!-- beyin-session:<sha256(session_id)[:24]> -->
## 14:32–15:10 · codex · proje-alpha · 23 istem
- receipt: görev X tamamlandı → receipts/<hash>.md
- reflection: son promptlar hafıza güncellenmeden geçti
### Özet
<ajan doldurur; hook bu bölümün içeriğine asla dokunmaz>
```

- SessionStart: blok iskeleti `## OPEN · HH:MM · harness · proje` + boş `### Özet`
  eklenir; HTML-yorum anahtarı oturum eşleştirir (aynı anahtar tekrar gelirse yenisi
  eklenmez). SessionEnd: aynı anahtarlı bloğun başlığı kapatılır (bitiş saati + prompt
  sayısı), receipt/reflection satırları başlık altına eklenir; Özet body'sine dokunulmaz.
- Eşzamanlı oturumlar: portalock (flush.py'nin `_portalock` kalıbı) ile serialize;
  bloklar anahtarla ayrışır.
- `receipt` üretmez — yalnız var olanları referanslar (imza disiplini bozulmaz).

### Kapı ve hatırlatma

- `preferences --daily-log on|off`; **varsayılan `false`**, üç profilde de; profil
  değişimlerinde korunur (`secret_filter` kalıbı, `beyin_v3_preferences.py:50`).
- Kapalıysa: dosya oluşmaz, hiçbir şey enjekte edilmez.
- Hatırlatma **yalnız SessionStart** enjeksiyonunda tek satır (tur-başı strict bağlamına
  girmez): "Oturum bitmeden bugünün daily-log bloğundaki Özet'i beş bölüm şemasıyla
  doldur; kalıcı değer yoksa boş bırak." Tam süzme kuralları SKILL.md'de bir kez.
- Tur-başı enjeksiyon kirliliği riski YOK: passage yolu `daily/` ve `receipts/`'i
  her zaman dışlar (RUNTIME.md); log yalnız bilinçli `context`/aramada görünür — amaç bu.

### Emniyet kemerleri

1. **(bu işte)** Yarıda-kalan telafisi: SessionStart'ta yetim `session_start_time.*`
   state dosyası varsa (bitiş kaydı olmayan oturum) açık bloğun başlığı
   `## OPEN (yarıda kaldı) · ...` işaretlenir, state temizlenir. V2 bu vakada sessizdi.
2. **(Faz-2, ertelendi)** PreCompact kurtarma çizgisi — çökme-öncesi yarım blok.

## Kabul testleri (`tests/custom/v3_daily_log_test.py`)

1. Kapı kapalıyken (varsayılan) hiçbir dosya/enjeksiyon yok.
2. SessionStart→SessionEnd: blok `OPEN`'dan kapalı başlığa geçer; prompt sayısı ve
   saat aralığı doğru; frontmatter `type: episodic`.
3. Özet korunumu: ajan Özet'e metin yazdı → SessionEnd sonrası metin aynen durur.
4. Receipt referansı: oturum aralığındaki receipt log satırında görünür.
5. Yetim state → `yarıda kaldı` işareti + state temizliği.
6. Eşzamanlı iki oturum anahtarı: iki ayrı blok, tek dosya bozulmaz.
7. Enjeksiyon: hatırlatma yalnız SessionStart çıktısında, açıkken; kapalıyken yok.

## Reddedilenler

- V2 flush'ını diriltmek (model çağrısı): çatalın "model çağrılmaz / iddia imzalanır"
  sınırını kendi elimizle delerdi.
- V2 promptunun tamamını kopyalamak: transcript sarmalayıcı, "untrusted data" çerçevesi,
  `FLUSH_BOS` nöbeteri ve şema-retry yalnız ayrı model çağrısı için anlamlı; şema ve
  süzme kuralları alındı, çağrı artıkları alınmadı.
- Installer'da soru/bayrak: ürün duruşu "installer soru sormaz"; açma tek seferlik
  `preferences --daily-log on` (karar A).
- `daily/v3/{gün}.md`'ye yazmak: projeksiyon mülkiyeti; çakışırdı.
- Log'a receipt otomatığı: iddia üretimi olurdu (bkz. receipt tasarım gerekçesi).

## Bilinen sınırlar

- Not-düzeyi indeks dosyayı tek kayıt saydığı için proje filtreli sorgular proje-
  alanısız günlük logu göremez (`_eligible`: exact); log V2 gibi projeler-üstüdür.
- Çökme anındaki Özet boş kalabilir — olgu bloğu yine tamdır (Faz-2 kemer 2 bunu
  azaltır).
- PR tartışma başlığı ayrı olabilir; savunma: *"V3 oturum izini disipline bıraktı;
  biz izi mekanizmaya geri verdik — yoruma dokunmadan, model'siz, varsayılan kapalı."*

## Uygulama sırası

1. Kırmızı testler (yukarıdaki 7 vaka) → 2. `beyin_v3_sessionlog.py` + preferences
alanı + hook bağlama (`beyin_v3_hook.py`; `.ps1` çiftleri render'dan gelir) → 3. yeşil +
tam paket → 4. docs (RUNTIME/PREFERENCES/SKILL.md + record) → 5. commit + push.

## Uygulama sonucu

- `beyin_v3_sessionlog.py` (yeni): SessionStart blok açar / SessionEnd kapatır; portalock,
  atomic yazım, UTC-duyarlı receipt penceresi (`receipts` tablosu, sha256 kaynak yolu),
  TTL 8s'lik yetim-işaretleme, `needs_reflection` satırı. V2'den yalnız beş bölüm şeması
  ve süzme kuralları alındı; model çağrısı yok.
- `preferences.daily_log` üç profilde `False`; profil değişiminde korunur
  (`secret_filter` ile birlikte); kök CLI `preferences --daily-log on|off`.
- Hook: `settings = read()` hemen ardında senkron çağrı (queue worker'dan bağımsız),
  try/except ile hook'u asla kırmaz; hatırlatma yalnız SessionStart çıktısına eklenir.
- TDD: 8 test (kapı, aç/kapat başlık + prompt sayısı, Özet korunumu, receipt penceresi,
  yarıda-kalan, eşzamanlı iki oturum, restart'ta tek blok, gerçek hook subprocess
  telafi) → hedefli 8/8 → tam paket **746/746**.
- Test notu: `created_at` UTC + db `receipts.id` ham event_id (dosya adı sha256) —
  ilken testi bir kez tuzakladı; pencere kıyası now-aware'a çevrildi.
