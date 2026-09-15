# Public mimari incelemesi

Kapsam: main 2e074cc, salt okunur kod incelemesi. Gerçek model veya installer çalıştırılmadı.

## Güçlü taraflar
- Ortak script/hook store; Codex renderer mutlak yolları, ilgisiz hook korumasını ve atomik yazmayı sağlıyor: template/.claude/scripts/render_codex_hooks.py:44,66,118; scripts/upgrade.sh:448.
- Codex transcript adaptörü tool/reasoning yerine kullanıcı/assistant mesajlarını alıyor: template/.claude/scripts/flush.py:127.
- Compiler geçici staging, output allowlist, symlink/deletion reddi, source hash kontrolü ve dosya bazında atomik promotion kullanıyor: template/.claude/scripts/compile.py:325,443,509,637.

## Bulgular
1. Codex adaptörü bağımsız model motoru değil; varsayılan özet/derleme Claude CLI gerektiriyor. flush.py:485; compile.py:631.
2. Başarısız flush kalıcı retry kuyruğuna alınmıyor; finally hook girdisini siliyor. hooks/session-end.sh:49; flush.py:763,849.
3. Claude/Codex Stop checkpoint yok. Dedup yalnız 60 saniye; transcript cursor yok, son 30 mesaj/15.000 karakter sınırı var. render_codex_hooks.py:15; flush.py:32,210,312. Yeni içerik bastırılabilir veya eski içerik tekrarlanabilir.
4. Daily oluşturma ve append sessionlar arasında tek kilitle korunmuyor. exists/write_text yarışı ilk günlük içeriğini kaybettirebilir. flush.py:520,730. State vault içinde: hooks/lib.sh:12.
5. Compiler tüm output seti transaction değil; promotion sırasında kısmi başarı kalabilir. compile.py:533. CAS kontrolü ile kopyalama arasındaki eşzamanlı edit penceresi de açık.
6. Last-Session/Threads güncellemesi agent disiplinine bağlı; session-end mtime kontrolü başka session yazısını başarı sanabilir. template/CLAUDE.md:33; hooks/session-end.sh:36.
7. Upgrade snapshot + finalize gate olumlu ama yerinde cp için otomatik rollback yok. scripts/upgrade.sh:149,347,782. git add -u -- . allowlist dışında eşzamanlı tracked değişiklikleri commit'e alabilir: 787-803.

## Test kanıtı ve boşluklar
PYTHONDONTWRITEBYTECODE=1 python3 tests/scripts_test.py: 36/36 geçti, 7.048 saniye, exit 0. Geçici vault/model stub kullanıldı. Repo değiştirilmedi.
Mevcut yeşil suite yukarıdaki issue'ları çürütmez: 60 saniye içinde yeni transcript suffix, 60 saniye sonra aynı transcript replay, farklı sessionların ilk daily oluşturma yarışı, flush failure sonrası otomatik retry, ikinci promotion kopyasında hata/rollback, upgrade sırasında allowlist dışı tracked edit ve gerçek Desktop lifecycle için özel regresyon kanıtı yok. Bu senaryolar yeni ortak runtime kabul kapılarına eklenmeli.
