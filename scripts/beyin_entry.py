#!/usr/bin/env python3
"""Vault-local entry point; configuration contains no credentials."""
from contextlib import redirect_stdout, redirect_stderr
import io
import importlib.util
import json
from pathlib import Path
import sys
sys.dont_write_bytecode = True



def human_result(result, command, installed_version=None):
    status = result.get('status', '')
    if result.get('error'):
        return 'Islem tamamlanamadi: ' + str(result.get('message', result['error']))
    if command == 'preferences':
        prefs = result['preferences']
        return ('Otomatik kontrol: ' + ('acik' if prefs['auto_sync'] else 'kapali') +
                '\nKontrol araligi: ' + str(prefs['interval_minutes']) + ' dakika (0 = her olay)' +
                '\nOtomatik baglam: ' + prefs['context_mode'] +
                '\nBaglam ust siniri: ' + str(prefs['context_chars']) + ' karakter' +
                '\nSir suzgeci: ' + ('acik' if prefs['secret_filter'] else 'kapali') +
                '\nYerel kontroller model cagirmaz. Zamanlayici kurulmaz.')
    if command == 'doctor':
        labels = {'never_seen': 'Henuz gercek istemci oturumu gozlenmedi.',
                  'observed_metadata': 'Oturum olaylari gozleniyor.',
                  'pending': 'Bekleyen isler var.', 'needs_attention': 'Kontrol gerektiren bir sorun var.'}
        lines = ['Beyin ' + (installed_version or 'surumu bilinmiyor'), labels.get(status, 'Saglik kontrolu tamamlandi.'),
                 'Bekleyen is: ' + str(result.get('pending_events', 0))]
        for name, details in result.get('lifecycle', {}).items():
            lines.append(name + ': ' + ('olay goruldu' if details.get('status') == 'observed_metadata' else 'henuz dogrulanmadi'))
        if result.get('secrets_redacted'):
            lines.append('Sir suzgeci ' + str(result['secrets_redacted']) + ' eslesmeyi [REDACTED] olarak yazdi.')
        if result.get('skill_conflicts'):
            lines.append('Skill kopyalari ayristi: ' + ', '.join(result['skill_conflicts']) + '. Iki surum de korundu.')
        if result.get('skill_unmanaged'):
            lines.append('Skill klasorundeki yonetilmeyen girdiler (bilgi): ' + ', '.join(result['skill_unmanaged']) + '.')
        if status in ('needs_attention', 'pending'):
            lines.append('Ajanina "beyin doktor" diyerek ayrintiyi inceletebilirsin.')
        return '\n'.join(lines)
    if status == 'updated':
        message = 'Beyin guncellendi: ' + str(result.get('from_version', installed_version or '?')) + ' -> ' + str(result['version'])
    elif status == 'available':
        message = 'Yeni surum var: ' + str(result.get('current_version', '?')) + ' -> ' + str(result['version']) + '\nGuncellemek icin: python beyin.py update'
    elif status == 'noop':
        message = 'Beyin guncel: ' + str(result.get('version', installed_version or '?'))
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
            args = parser.parse_args(argv)
            if args.command == 'update': result = updater.update(vault, state, args.package, args.check)
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
