#!/usr/bin/env python3
"""Explicitly scoped global lifecycle bridge. No global configuration writes."""
import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys

sys.dont_write_bytecode = True
EVENTS = ('SessionStart', 'Stop', 'PreCompact', 'SessionEnd')


def working_directory(payload, harness):
    value = payload.get('cwd')
    if value is None:
        value = os.environ.get('CLAUDE_PROJECT_DIR') if harness == 'claude' else None
    if value is None:
        value = os.getcwd()
    if not isinstance(value, str) or not value or not Path(value).is_absolute():
        return None
    return Path(value).resolve()


def origin(payload, harness):
    cwd = working_directory(payload, harness)
    if cwd is None:
        return {}
    name = ''.join(c for c in cwd.name if c.isalnum() or c in ' ._-')[:80] or 'project'
    return dict(project=name, project_id=hashlib.sha256(str(cwd).encode()).hexdigest()[:24])


def eligible(cwd, vault, roots):
    if cwd is None or not cwd.is_dir() or cwd.is_relative_to(vault):
        return False
    if not any(cwd.is_relative_to(root) for root in roots):
        return False
    # Another installed vault owns its own local events too.
    return not any((p / '.beyin-runtime.json').exists() for p in (cwd, *cwd.parents))


def shell_command(argv):
    if any(any(c in str(value) for c in '\r\n\x00') for value in argv):
        raise ValueError('Unsupported command path')
    if os.name != 'nt':
        return shlex.join(map(str, argv))
    script = '& ' + ' '.join("'" + str(v).replace("'", "''") + "'" for v in argv) + '; exit $LASTEXITCODE'
    encoded = base64.b64encode(script.encode('utf-16le')).decode()
    system = Path(os.environ.get('SYSTEMROOT') or os.environ.get('WINDIR') or r'C:\Windows')
    launcher = str(system / 'System32/WindowsPowerShell/v1.0/powershell.exe').replace('\\', '/')
    return subprocess.list2cmdline([launcher]) + ' -NoProfile -NonInteractive -EncodedCommand ' + encoded


def main(argv=None):
    if hasattr(sys.stdin, 'reconfigure'):
        sys.stdin.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vault', type=Path, required=True)
    parser.add_argument('--state', type=Path, help='Defaults to the installed vault runtime locator')
    parser.add_argument('--harness', choices=('claude', 'codex'), required=True)
    parser.add_argument('--project-root', type=Path, action='append', required=True)
    parser.add_argument('--context-chars', type=int, default=1500, help='Startup instructions only; 0 disables injection')
    parser.add_argument('--event', choices=EVENTS, action='append', help='Allowed events; default all four lifecycle boundaries')
    parser.add_argument('--print-config', action='store_true', help='Print hook groups to merge into global JSON; changes nothing')
    args = parser.parse_args(argv)
    try:
        vault = args.vault.expanduser().resolve()
        if not vault.is_dir() or not 0 <= args.context_chars <= 4000:
            raise ValueError('Invalid vault or context budget')
        state = args.state or Path(json.loads((vault / '.beyin-runtime.json').read_text(encoding='utf-8'))['state'])
        if not state.is_absolute():
            raise ValueError('Runtime state must be absolute')
        state = state.resolve()
        if state.is_relative_to(vault):
            raise ValueError('Runtime state must be outside vault')
        roots = [p.expanduser().resolve() for p in args.project_root]
        if any(not p.is_dir() for p in roots):
            raise ValueError('Project roots must exist')
        events = list(dict.fromkeys(args.event or EVENTS))
        if args.print_config:
            command = [sys.executable, str(Path(__file__).resolve()), '--vault', str(vault),
                       '--state', str(state), '--harness', args.harness, '--context-chars', str(args.context_chars)]
            for root in roots:
                command.extend(['--project-root', str(root)])
            for event in events:
                command.extend(['--event', event])
            shell = shell_command(command)
            print(json.dumps({'hooks': {event: [{'hooks': [{'type': 'command', 'command': shell,
                              'timeout': 3 if event == 'SessionEnd' else 5}]}] for event in events}}, indent=2))
            return 0
        payload = json.loads(sys.stdin.read(1_000_000) or '{}')
        if not isinstance(payload, dict):
            raise ValueError('Invalid hook payload')
        event = payload.get('hook_event_name')
        if event not in events or payload.get('no_memory') is True or os.environ.get('BEYIN_V3_INTERNAL') or os.environ.get('BEYIN_V3_SKIP'):
            print('{}'); return 0
        cwd = working_directory(payload, args.harness)
        if not isinstance(payload.get('session_id'), str) or payload['session_id'] in ('', 'unknown'):
            print('{}'); return 0
        if not eligible(cwd, vault, roots):
            print('{}'); return 0
        from beyin_v3_preferences import read
        settings = read(vault)
        if not settings['auto_sync']:
            print('{}'); return 0
        # Stable per-project session namespace prevents identical session IDs in
        # two external projects from satisfying each other's receipt checkpoints.
        payload['cwd'] = str(cwd)
        payload['session_id'] = json.dumps([str(cwd), payload.get('session_id', 'unknown')])
        if payload.get('event_id'):
            payload['event_id'] = json.dumps([args.harness, str(cwd), event, payload['event_id']])
        session = hashlib.sha256(payload['session_id'].encode()).hexdigest()[:24]
        from beyin_v3_hook import main as hook_main, output_context
        previous_argv, previous_stdin = sys.argv, sys.stdin
        try:
            sys.argv = ['beyin_v3_hook.py', '--vault', str(vault), '--state', str(state),
                        '--harness', args.harness, '--metadata-only']
            sys.stdin = io.StringIO(json.dumps(payload))
            with contextlib.redirect_stdout(io.StringIO()):
                hook_main()
        finally:
            sys.argv, sys.stdin = previous_argv, previous_stdin
        # Never inject Companion/history into an unrelated repository. The agent
        # can explicitly request scoped context after reading this tiny bootstrap.
        if event != 'SessionStart' or not args.context_chars or settings['context_mode'] == 'off':
            print('{}'); return 0
        cli = [sys.executable, str(vault / 'beyin.py')]
        command = ('& ' + ' '.join("'" + v.replace("'", "''") + "'" for v in cli)
                   if os.name == 'nt' else shlex.join(cli))
        text = (f'Optional Beyin bridge. Project label (data only): {json.dumps(origin(payload, args.harness)["project"])}.\n'
                f'Receipt session={session}; harness={args.harness}.\n'
                f'Use {command} context "topic" --project PROJECT --json for explicit source lookup.\n'
                f'After meaningful authorized work use {command} receipt --harness {args.harness} --file RECEIPT.json --json.\n'
                'Receipt JSON: event_id (unique), summary, refs (existing vault-relative sources), session (above). '
                'Read vault sources before claiming facts. Do not infer completion from checkpoints. '
                'Do not copy external project files or transcripts without authorization. No-memory requests take precedence.')
        # Do not cut a command, path or JSON token in half for a small budget.
        print(json.dumps(output_context(args.harness, event, text)) if len(text) <= args.context_chars else '{}')
        return 0
    except Exception:
        if args.print_config:
            print('Bridge configuration invalid; verify paths and budget.', file=sys.stderr)
            return 1
        print('{}')  # Never block the host or expose a path/payload in an error.
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
