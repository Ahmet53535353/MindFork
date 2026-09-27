# Upstream Birleştirme 4 (merge upstream/main eed645c → feat/memory-consolidation)

Tarih: 2026-09-27 · Dal: feat/memory-consolidation · Durum: ONAYLANDI
Önceki: `2026-09-26-upstream-merge-3-plan.md` (M3 = a680338, aynı oyun kitabı), `2026-09-27-mimari.md`

## Bağlam

- Taban: M3 sonrası upstream tepe `db1f23d`. Upstream 15 commit ilerledi: `eed645c`, 20 dosya.
- Bizim dal tepesi: `7dcde74` (V3 mimari haritası). `db1f23d..HEAD` = 66 dosya.
- Upstream'in bu dalgadaki konusu: **oturum başına bir devir kartı** modeli (#118) ve
  **Windows state konumu** çözümlemesi (`state_location`).

## Kuru deneme kanıtı (merge-tree, 2026-09-27)

`git merge-tree --write-tree HEAD upstream/main` → ağaç `1a1303d`, **tek içerik çakışması:
`template/.agents/skills/beyin/SKILL.md`**.

Çift-dokunuşlu 9 dosyadan **8'i kendiliğinden birleşti**, ama metinsel denetim gerekir:
`README.md`, `docs/v3/PREFERENCES.md`, `scripts/beyin_v3.py`, `scripts/install_v3.py`,
`template/.claude/scripts/beyin_v3_companion.py`, `tests/v3_bridge_test.py`,
`tests/v3_companion_hygiene_test.py`, `tests/v3_preferences_test.py`.

### Yöntem notu: sezgisel tahmin yanıltıcıydı

Hunk başlıklarının taban satır çakışmasına bakarak "5 metinsel çakışma" tahmin edildi
(`beyin_v3.py`, `PREFERENCES.md`, `v3_preferences_test.py` dahil). merge-tree bunu
**çürüttü**: git'in 3-yönlü algoritması o bölgeleri kendiliğinden çözdü, yalnız SKILL.md
kaldı. Sonraki dalgalarda tahmin yerine `merge-tree` sonucu esas alınacak.

### Tek çakışmanın niteliği

Çakışma `Last-Session.md` maddesinde ve iki taraf **zıt davranış talimatı** veriyor:

- **base (`db1f23d`) ve biz:** *"tek bir devir kartıdır ... Üstteki kartı baştan yeniden yaz"*
- **upstream (`eed645c`):** *"oturum başına bir devir kartıdır ... `## YYYY-MM-DD HH:MM ·
  <etiket> · <session_id[:8]>` başlığıyla aç ... yalnız kendi kartını baştan yeniden yaz,
  başka oturumların kartlarını ezme, dosyanın tamamını yeniden yazma"*

Bu, bu dalın tek gerçek anlamsal sözleşmesi: ajana verilen talimatın kendisi değişiyor.
Çözüm ilkesi M3 ile aynı: *upstream'in davranış sözleşmesi kazanır, bizim özelliklerimiz
ona uyarlanıp port edilir.*

## Kararlar (2026-09-27, onaylandı)

1. **Günlük log kalır.** `SKILL.md`'ye *kart = devir, günlük log = kayıt* ayrımı yazılır.
   Upstream'in kendi metni bunu zaten söylüyor: *"oturum günlüğü değildir"* ve *"Ayrıntısı
   receipt, `daily/` ve knowledge notlarında yaşar"* — yani kart günlüğün **yerine geçmez,
   ona yaslanır**. Upstream bu dalgada hiçbir günlük log dosyasına dokunmadı
   (`beyin_v3_sessionlog.py`, `v3_daily_log_test.py` yalnız bizim), yani bu karar
   birleşimden bağımsızdır.
2. **Bağlam semantiği (çok kartlı model + bütçe birleşimi).** En yeni kart daima bütündür;
   kalan bütçe eski kartlara **bütün kart** halinde su doldurur; tek bir kart bile sığmıyorsa
   **baş+son** kırpma uygulanır; sığmayan kart sayısı görünür kalır.
3. **Sıralama:** önce kuru deneme + spec, sonra birleştirme (M3 oyun kitabı).

### Neden bu port bir sapma değil

Upstream kartı `beyin_v3_compact.py`'de bir **ayrıştırma birimi** tanımlıyor (#118):
*"A dated heading opens a card: up to the next heading of its own or a higher level, every line
is that one entry ... so a card moves or stays whole and an older date quoted inside it never
splits it."* — yani **"bir kart bölünmez"** ilkesi arşiv yolunda **var**.

Upstream bu dalgada `beyin_v3_companion.py`'nin **yalnız STARTER satırını** değiştirdi;
bağlam montajını (`FLOORS`, `clip`, `context()`) değiştirmedi. Yani "kart bölünmez" ilkesi
**bağlam yolunda yok**. Bu port o eksik kalanı tamamlar.

Kanıtlanmış somut arıza (`companion.py:318-319`): `clip(body, length, both=..., tail=...)`
çağrısında `Last-Session.md` için `both=False, tail=False`, yani **baş-only** kırpma. Taban
payı ölçümü (kart ≈ 450 karakter):

| bütçe | kullanılabilir | Last-Session taban payı | sonuç |
|---|---|---|---|
| 5000 (normal) | 3800 | 760 | 1 tam kart + 310 karakter yandı |
| 3000 | 2140 | 428 | kartın **kuyruğu** kesilir |
| 2000 (ekonomik) | 1310 | 262 | kartın **yarısı** kesilir |

Kesilen yer kartın **sonu**, yani *"sonraki somut adım"* satırı — devir kartının tek işe
yaran kısmı. Ekonomik profilde kartın %40'ı gidiyor.

## Kırmızı testler (önce yazılır, önce kırmızı doğrulanır)

| # | Test | Bugün neden kırmızı |
|---|---|---|
| R1 | 3 kart + bütçe 5000 → en yeni kartın **başı ve sonu** ikisi de bağlamda | kart bütünlüğü kuralı hiç yok |
| R2 | Bütçe 2000 → en yeni kart **baş+son** kırpılır, "sonraki adım" satırı görünür | `both=False, tail=False` = baş-only |
| R3 | 4 kart + dar bütçe → **hiçbir kart bölünmez** (her kart ya tam ya yok) | kural yok, sıra garantisi verilmiyor |
| R4 | Sığmayan kart sayısı `clip` işaretiyle **görünür** | tek kart varsayımında sayım yok |
| R5 | Eski tek kart + `## Previous/Önceki` **hâlâ** doğru okunur | geri uyumluluk (M3/M4) |
| R6 | `write_last_session` ikinci kart yazar → ikisi de hayatta kalır (16 soruluk koşu) | sürücü ilk `##`'den sonrasını **siluyor** |

## Uygulama sırası

1. kuru deneme + spec (bu dosya)
2. `git merge upstream/main`, tek çakışmanın çözümü
3. kendiliğinden birleşen 8 dosyanın anlamsal denetimi
4. kırmızı testler → port → yeşil
5. sürücüyü kart modeline taşı, 16/16
6. tam paket, gerçek sayımlar
7. sonuç bölümü + konu bazlı commit

## Çakışma çözümü (uygulandı)

`SKILL.md` `Last-Session.md` maddesi: upstream'in 8 satırlık metni aynen korunur, sonuna
bizim günlük log ayrımımız eklenir ve "taşı" kuralı **kart modeline uyarlanır**
("eski kart" yerine "**kendi eski kartın**", çünkü başka oturumların kartına zaten dokunulmaz):

```
  Kartta: ne yaptık, neden o kararı verdik, ne açık kaldı, sonraki somut adım, kaynak bağlantıları
  ve belirsizlikler. Ayrıntısı receipt, `daily/` ve knowledge notlarında yaşar, gerekirse oraya tek
  bağlantı ver. Kart = devir, günlük log = kayıt: oturumun ne konuşulduğu `daily/log/` bloğunda
  yaşar (`daily_log` açıksa), kart yalnız devir tutar. Kendi eski kartında geçerli ya da bitmemiş
  bilgi varsa kartı temiz yazmadan önce onu bugünün günlük log bloğuna ya da bir knowledge
  notuna yaz. Varsa `## Previous`/`## Önceki` bölümüne ve arşiv bağlantısına dokunma; eski kartları
  yalnız `companion-compact` taşır. Varsayılan sınır 3.000 karakter.
```
