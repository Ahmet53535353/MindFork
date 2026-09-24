#!/usr/bin/env python3
"""Vault-local entry point; configuration contains no credentials."""
from contextlib import redirect_stdout, redirect_stderr
import io
import importlib.util
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True



JEV_MODES = {'off': 'kapali', 'shadow': 'golge', 'on': 'acik'}


def update_lines(result):
    status = result.get('status', 'unknown')
    if status == 'available':
        command = 'py -3' if sys.platform == 'win32' else 'python3'
        lines = ['Yeni surum: ' + result['version'],
                 'Surum notlari: ' + result['release_url'],
                 'Guncelle: ' + command + ' beyin.py update']
    else:
        messages = {'disabled': 'Surum bildirimleri kapali.', 'unknown': 'Surum kontrolu henuz yapilmadi.',
                'unavailable': 'Surum kontrolu yapilamadi; guncellik dogrulanmadi.',
                'up_to_date': 'Beyin guncel: ' + str(result.get('current_version', '?')),
                'ahead': 'Kurulu surum resmi stable surumden ileride.'}
        lines = [messages.get(status, 'Surum bilgisi alinamadi.')]
    if result.get('checked_at'):
        from datetime import datetime, timezone
        lines.append('Son kontrol: ' + datetime.fromtimestamp(result['checked_at'], timezone.utc).isoformat())
    return lines


def jev_lines(result):
    """Shared by the jev command and the doctor summary; reads only reported fields."""
    lines = []
    if result.get('automatic_model_calls'):
        lines.append('Otomatik baglam acik: her turda istemin ve en fazla 8 aday ic/kamu notunun basligi ile'
                     ' ilk 600 karakteri saglayiciya gider. Ozel notlar gonderilmez.')
    if result.get('mode', 'off') != 'off' and not result.get('key_present'):
        lines.append('TYPESAFE_API_KEY yok: cagrilar yerel sonuca duser.')
    return lines


def human_result(result, command, installed_version=None):
    status = result.get('status', '')
    if result.get('error'):
        return 'Islem tamamlanamadi: ' + str(result.get('message', result['error']))
    if command == 'jev':
        features = result.get('features', {})
        lines = ['Jev: ' + JEV_MODES.get(result.get('mode'), 'bilinmiyor') +
                 (' (kayitli: ' + JEV_MODES.get(result.get('saved_mode'), 'bilinmiyor') + ')'
                  if result.get('kill_switch') else ''),
                 'Ozellikler: ' + (', '.join(name + ' ' + ('acik' if value else 'kapali')
                                             for name, value in features.items()) or 'yok'),
                 'Anahtar: ' + ('var' if result.get('key_present') else 'yok'),
                 'Acil kapatma: ' + ('acik' if result.get('kill_switch') else 'kapali'),
                 'Son 24 saat: ' + str(result.get('last_24h', {}).get('calls', 0)) + ' cagri']
        if not result.get('config_valid', True):
            lines.append('Ayar dosyasi bozuk; jev.json elle duzeltilmeli.')
        return '\n'.join(lines + jev_lines(result))
    if command == 'preferences':
        prefs = result['preferences']
        return ('Otomatik kontrol: ' + ('acik' if prefs['auto_sync'] else 'kapali') +
                '\nKontrol araligi: ' + str(prefs['interval_minutes']) + ' dakika (0 = her olay)' +
                '\nOtomatik baglam: ' + prefs['context_mode'] +
                '\nBaglam ust siniri: ' + str(prefs['context_chars']) + ' karakter' +
                '\nSir suzgeci: ' + ('acik' if prefs['secret_filter'] else 'kapali') +
                '\nSurum bildirimi: ' + ('acik' if result.get('update_notifications', {}).get('effective') else 'kapali') +
                ''.join('\nHafiza dosyasi siniri, ' + name + ': ' + (str(value) + ' karakter' if value else 'kapali')
                        for name, value in (result.get('companion_limits') or {}).items()) +
                '\nAcikken gunde en fazla bir kez GitHub surum bilgisi okunur; notlar gonderilmez.' +
                '\nYerel kontroller model cagirmaz. Zamanlayici kurulmaz.')
    if command == 'companion-compact':
        lines = []
        for name, entry in result.get('files', {}).items():
            if entry.get('status') in ('compacted', 'planned'):
                lines.append(name + ': ' + str(entry.get('chars')) + ' -> ' + str(entry.get('chars_after')) + ' karakter' +
                             (' olacak' if entry['status'] == 'planned' else '') + ', ' + str(entry.get('moved_chars')) +
                             ' karakter arsive ' + ('tasinacak' if entry['status'] == 'planned' else 'tasindi') + '.')
                if not entry.get('within_limit_after'):
                    lines.append(name + ' hala sinirin (' + str(entry.get('limit')) + ') ustunde; dosyayi sinir icinde yeniden yaz.')
            elif entry.get('status') == 'needs_rewrite':
                lines.append(name + ': tasinacak tarihli eski kayit yok; dosyayi sinir icinde yeniden yaz.')
            elif entry.get('status') == 'conflict':
                lines.append(name + ': islem sirasinda dosya degisti; hicbir sey tasinmadi, tekrar dene.')
            elif entry.get('status') == 'needs_attention':
                lines.append(name + ': ' + str(entry.get('reason', 'kontrol gerekiyor')) + '.')
            elif entry.get('status') in ('within_limit', 'limit_off'):
                lines.append(name + ': sinir icinde, degisiklik yok.')
        if result.get('status') == 'needs_attention' and not result.get('files'):
            lines.append('Sinir ayari okunamadi; hicbir sey tasinmadi.' if result.get('limits_file') == 'invalid'
                         else 'Birden fazla companion klasoru var; hicbir sey tasinmadi.')
        return '\n'.join(lines + ['Hicbir metin silinmedi; model cagrilmadi.'])
    if command == 'doctor':
        labels = {'never_seen': 'Henuz gercek istemci oturumu gozlenmedi.',
                  'observed_metadata': 'Oturum olaylari gozleniyor.',
                  'pending': 'Bekleyen isler var.', 'needs_attention': 'Kontrol gerektiren bir sorun var.'}
        lines = ['Beyin ' + (installed_version or 'surumu bilinmiyor'), labels.get(status, 'Saglik kontrolu tamamlandi.'),
                 'Bekleyen is: ' + str(result.get('pending_events', 0))]
        for name, details in result.get('lifecycle', {}).items():
            lines.append(name + ': ' + ('olay goruldu' if details.get('status') == 'observed_metadata' else 'henuz dogrulanmadi'))
        jev = result.get('jev') or {}
        if jev.get('mode', 'off') == 'off':
            lines.append('Jev: kapali')
        else:
            lines.append('Jev: ' + JEV_MODES.get(jev['mode'], 'bilinmiyor') + ' (otomatik baglam: ' +
                         ('acik' if jev.get('automatic_model_calls') else 'kapali') + '), son 24 saat ' +
                         str(jev.get('last_24h', {}).get('calls', 0)) + ' cagri')
        if result.get('secrets_redacted'):
            lines.append('Sir suzgeci ' + str(result['secrets_redacted']) + ' eslesmeyi [REDACTED] olarak yazdi.')
        if result.get('skill_conflicts'):
            lines.append('Skill kopyalari ayristi: ' + ', '.join(result['skill_conflicts']) + '. Iki surum de korundu.')
        if result.get('skill_unmanaged'):
            lines.append('Skill klasorundeki yonetilmeyen girdiler (bilgi): ' + ', '.join(result['skill_unmanaged']) + '.')
        hygiene = result.get('companion_hygiene') or {}
        for name in hygiene.get('over_limit', []):
            entry = hygiene['files'][name]
            lines.append('Hafiza hijyeni: ' + name + ' ' + str(entry['chars']) + ' karakter (sinir ' + str(entry['limit']) +
                         '). Ajanina "' + ('py -3' if sys.platform == 'win32' else 'python3') +
                         ' beyin.py companion-compact" calistirmasini soyle; eski kayitlar arsive tasinir, metin silinmez.')
        if status in ('needs_attention', 'pending'):
            lines.append('Ajanina "beyin doktor" diyerek ayrintiyi inceletebilirsin.')
        return '\n'.join(lines + update_lines(result.get('updates', {})))
    if result.get('verification') == 'metadata_only':
        return '\n'.join(update_lines(result) + ['Yalniz surum bilgisi kontrol edildi; paket kurulumu denenmedi.'])
    if status == 'updated':
        message = 'Beyin guncellendi: ' + str(result.get('from_version', installed_version or '?')) + ' -> ' + str(result['version'])
    elif status == 'available':
        message = 'Yeni surum var: ' + str(result.get('current_version', '?')) + ' -> ' + str(result['version']) + '\nGuncellemek icin: python beyin.py update'
    elif status == 'noop':
        message = 'Beyin guncel: ' + str(result.get('version', installed_version or '?'))
    elif status == 'dismissed':
        message = 'Bu surumun oturum bildirimi susturuldu: ' + result['version']
    elif status == 'uninstalled':
        message = 'Kurulum geri alindi. Kullanici notlari korundu.'
    elif status == 'rolled_back':
        message = 'Onceki surume donuldu: ' + str(result.get('version', '?'))
    elif status == 'recovered':
        message = 'Yarim kalan islem kurtarildi. Surum: ' + str(result.get('version', '?'))
    elif command == 'context':
        records = result.get('records', [])
        message = '\n\n'.join(str(r.get('source', '')) + '\n' + str(r.get('text', '')) for r in records) or 'Eslesen kaynak bulunamadi.'
    else:
        message = 'Islem sonucu: ' + str(status or 'tamamlandi')
    if result.get('trust_review_required'):
        message += '\nHook tanimi degisti: Codex /hooks guven incelemesini tamamla ve yeni oturum ac.'
    return message


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    human = ('--human' in argv or sys.stdout.isatty()) and '--json' not in argv
    argv = [arg for arg in argv if arg not in ('--human', '--json')]
    command = argv[0] if argv else 'doctor'
    vault = Path(__file__).resolve().parent
    stamp = vault / '.beyin-version'
    installed_version = None
    try:
        installed_version = stamp.read_text(encoding='utf-8').strip() if stamp.is_file() else None
        config_path = vault / '.beyin-runtime.json'
        if not config_path.is_file():
            raise ValueError('Kurulum ayari eksik; resmi V3 installer ile bu vault kurulumunu tamamlayin.')
        config = json.loads(config_path.read_text(encoding='utf-8'))
        state = Path(config['state'])
        directory = vault / '.claude/scripts'
        sys.path.insert(0, str(directory))
        if argv and argv[0] in ('update', 'rollback', 'recover'):
            import argparse
            import beyin_v3_update as updater
            parser = argparse.ArgumentParser()
            parser.add_argument('command', choices=('update', 'rollback', 'recover'))
            parser.add_argument('--check', action='store_true')
            parser.add_argument('--package', type=Path)
            parser.add_argument('--metadata-only', action='store_true')
            parser.add_argument('--dismiss')
            args = parser.parse_args(argv)
            if args.command != 'update' and (args.check or args.package or args.metadata_only or args.dismiss is not None):
                parser.error('update options require the update command')
            if args.metadata_only and (not args.check or args.package or args.dismiss is not None):
                parser.error('--metadata-only requires --check and cannot use --package or --dismiss')
            if args.dismiss is not None and (args.check or args.package):
                parser.error('--dismiss cannot use --check or --package')
            if args.command == 'update':
                import beyin_v3_releases as releases
                if args.metadata_only: result = releases.check(vault)
                elif args.dismiss is not None: result = releases.dismiss(vault, state, args.dismiss)
                else: result = updater.update(vault, state, args.package, args.check)
            elif args.command == 'rollback': result = updater.rollback(vault, state)
            else: result = updater.recover(vault, state)
            print(human_result(result, command, installed_version) if human else json.dumps(result, ensure_ascii=True, indent=2))
            return 0
        spec = importlib.util.spec_from_file_location('beyin_installed_cli', directory / 'beyin_v3_cli.py')
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        cli_args = ['--vault', str(vault), '--state', str(state)] + (argv or ['doctor'])
        if not human:
            return cli.main(cli_args)
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = cli.main(cli_args)
        value = output.getvalue() if not code else error.getvalue()
        try:
            result = json.loads(value)
            message = human_result(result, command, installed_version)
        except (ValueError, TypeError, AttributeError):
            message = 'Islem tamamlanamadi; ayrinti icin ayni komutu --json ile calistir.' if code else value.strip()
        print(message, file=sys.stderr if code else sys.stdout)
        return code
    except Exception as exc:
        error = {'error': type(exc).__name__, 'message': str(exc)}
        print(human_result(error, command, installed_version) if human else json.dumps(error, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
