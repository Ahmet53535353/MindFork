# Ortak runtime parity incelemesi

Kapsam: public main 2e074cc ile yerel .claude/hooks/vault_runtime/engine.py ve scripts/VAULT-AUTOMATION.md karşılaştırıldı. Yerel yalnız bu iki dosya okundu; canlı runtime, servis, model ve installer çalıştırılmadı. Hesap, özel kayıt veya kimlik içeriği okunmadı. Yerel compiler implementasyonu izinli kapsam dışında olduğundan onun staging güvenliği doğrulanmış değildir.

## Sonuç
Yerel engine kalıcı spool/SQLite, tek writer, journal recovery, transcript cursor, structured receipt ve revision kontrolüyle public lifecycle'ın önemli açıklarını karşılayabilecek bir temel. Ancak birebir kopyalama parity sağlamaz: platform bağımlılıkları, parser gerilemesi, conflict sonucunun başarısız işe dönüşmemesi ve özel vault'a sabitlenmiş yollar ayrıştırılmalı. Public compiler'ın güvenlik katmanı korunmalı; yerel projection engine onun yerine geçen bir compiler değildir.

## Kaybolmaması gereken public özellikler
- Compiler isolated staging; symlink, deletion, output allowlist ve kaynak değişimi kontrolü. Public template/.claude/scripts/compile.py:325,384,443,471,637. Yerel engine model çağırmaz; safe_path yalnız kök dışına kaçışı reddeder, bütün symlinkleri reddeden compiler manifest politikasının eşdeğeri değildir (engine.py:246).
- Dosya bazında atomik promotion, fsync ve hash bazlı ingestion. Public compile.py:509,851. Yerel journal bunu tamamlayabilir; bütün derleme setinin atomikliği ayrıca tasarlanmalı.
- Recursion guard, araçsız özet runner, compiler sınırlı araç listesi ve zaman aşımı. Public flush.py:383; compile.py:553. Compiler izolasyonu yalnız prompt disipliniyle değiştirilmemeli.
- Codex event_msg item_completed varyantları: public flush.py:139; yerel normalize yalnız user_message/agent_message okuyor (engine.py:103). Public varyant desteği korunmalı ve golden fixture ile test edilmeli.
- Public platform kilitleme adaptörü, Windows installer/PowerShell hook desteği. Yerelde doğrudan fcntl, os.uname ve macOS varsayılan state dizini var (engine.py:7,121,180). Public sürüme taşımak platform adapter gerektirir.
- Renderer ilgisiz hook koruması ve idempotent wiring; upgrade snapshot, korunmuş özel ayarlar, finalize gate ve en son version stamp. Public render_codex_hooks.py:66,118; scripts/upgrade.sh:347,496,782,820. Bunlar journal runtime kurulurken atlanmamalı.

## Yerel engine'den alınacaklar ve düzeltilecekler
- Alınacak: küçük metadata spool (168-175), dış runtime/tek writer (121-157), commit-before-effect journal ve recovery (221-265), incremental cursor (267-312), event retry/dead-letter (518-549), task expected revision (555-576), kaynak bazlı projection ve evidence-kind sınırı.
- Conflict başarı değildir: receipt(), owned_write() false sonucunu kontrol etmeden receipt-session meta yazıp pending'i siliyor (340-369); run() bunu succeeded yapıyor (537-539). Kaynak receipt veya daily yazısı korunup reddedildiğinde event conflict/retry olmalı, gap kapanmamalı.
- exactly-once iddiası yerine idempotent etkiler: sabit event_id korunmalı, tekrar event aynı payload değilse reddedilmeli. Mevcut enqueue aynı spool adına yazıyor, DB INSERT OR IGNORE ilk payload'ı tutuyor (168-173,528). Collision/mutated retry açık hata üretmeli.
- Tek writer yalnız yerel OS kilidi sağlar. Belgeler distributed SQLite olmadığını doğru söylüyor (VAULT-AUTOMATION.md:59-61); remote concurrent edit için revision/conflict çözümü gerekli.
- Receipt boşluğu heuristic'i doğrulanmış tamamlanma değildir: assistant metin uzunluğu kullanılıyor (engine.py:302). Structured receipt canonical olmalı, heuristic yalnız görünür uyarı üretmeli.

## Codex / Claude eşitliği için 8 kabul kriteri
1. Aynı source task, receipt schema ve deterministic projection: aynı fixture sonucu harness adı hariç aynı olmalı; model runner zorunluluğu harness'tan bağımsız olmalı.
2. CLI ve Desktop'ta ayrı cold-session gerçek lifecycle teslimi: SessionStart, prompt, Stop, PreCompact, SessionEnd; SessionEnd süre sınırı içinde yalnız enqueue. Config hash veya fixture gerçek teslim yerine geçmez (belge:65).
3. Aynı event tekrar tesliminde tek source receipt/daily marker; farklı içerikte aynı event_id açık conflict. Yeni transcript suffix 60 saniye içinde kaybolmamalı.
4. Crash injection: spool sonrası, DB commit sonrası, dosya replace öncesi/sonrası ve ikinci projection sırasında süreç kesilip yeniden başlatılınca kayıp/duplicate olmamalı; başarısız event retry/dead_letter görünmeli.
5. Parser golden fixture parity: Claude text blocks; Codex user_message, agent_message ve item_completed; malformed/partial JSONL, truncate/rotation, uzun transcript ve opt-out; reasoning/tool text notlara taşınmamalı.
6. Concurrency: iki harness aynı task revision ve daily üzerinde çalışınca tek writer, beklenen revision conflict ve korunmuş manual edit; false owned_write asla succeeded/gap-cleared olmamalı.
7. Compiler güvenlik regresyonları: public staging allowlist, symlink/deletion reddi, live-source hash, runner timeout/no recursive hook; çoklu dosya promotion için recoverable transaction. Actual local compiler ayrıca incelenmeden eşdeğer ilan edilmemeli.
8. Temiz kurulum/upgrade/rollback macOS ve Windows üzerinde: ilgisiz config/skills korunur; eski handlers inert; trust interaktif doğrulanır; kanonik source records kaybolmaz; allowlist dışı değişiklik commit edilmez.

## Migration riskleri ve sıra
- Önce layout/runtime config soyutlaması: yerel özel isimler/yollar public ürüne taşınmaz; yalnız gerekli algoritmalar port edilir.
- Public .state JSON ile yeni SQLite cursor/receipt journal arasında explicit schema migration ve eski log hash importu gerekir. Aksi halde daily tekrar derlenebilir veya geriye dönük kayıtlar atlanabilir.
- Eski daily auto-summary ile yeni structured receipt aynı anda açık bırakılmaz. Cutover boundary ve event watermark kaydedilir; önce enqueue doğrulanır, sonra eski handler inert hale getirilir.
- Public kişisel hafıza dosyalarının gövdesi korunur; generated view adoption snapshot ve hash karşılaştırmasıyla yapılır. Kullanıcı metni receipt gibi yeniden yorumlanmaz.
- Compiler schedule/model/bütçe ayrı politika olarak bırakılır. Yerel belgede ayrı model compiler korunuyor (VAULT-AUTOMATION.md:51); bu kod için staging eşdeğerliği henüz kanıt değil.
- Public upgrade snapshot olumlu ama rollback otomatik değil; yeni kurulum journal + explicit resume/rollback sağlamalı. git add -u -- . geniş kapsamı kaldırılmalı (scripts/upgrade.sh:802).

## Kanıt sınırı
Public model-stub suite 36/36 geçti; bu parity kriterlerini tek başına kapsamaz. Yerel engine için bu tur çalıştırılan test yoktur; bulgular salt okunur statik incelemedir. Özellikle conflict false sonucunun receipt başarı durumuna dönüşmesi ve parser varyant kaybı için yeni regresyon testleri gereklidir.

## Koordinatörün bağımsız sentetik doğrulama eki
Diğer inceleme ajanlarının koordinatöre bildirdiği kanıt: yerel receipt owned_write conflict halinde succeeded veriyor; public PR20 health parser JSONL beklediğinden compiler pretty JSON hata kaydını 0 hata gösterebiliyor ve warning girdisinde AttributeError oluşabiliyor. Bu alt inceleme bunları yeniden çalıştırmadı. İki hata da olduğu gibi taşınmamalı: receipt state geçişi bütün etkilerin sonucuna bağlı olmalı; health tek versiyonlu schema ile geçerli JSON/JSONL varyantlarını açıkça ele almalı, bozuk veya bilinmeyen kayıt sağlıklı sayılamamalı.
