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


def read_project_context(state):
    """Read machine-local project-context setting (default False). Rollback-safe outside vault."""
    path = Path(state) / 'project-context.json'
    if not path.is_file() or path.is_symlink():
        return False
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return bool(data.get('enabled', False))
    except (ValueError, OSError):
        return False


def save_project_context(state, enabled):
    """Save machine-local project-context setting atomically."""
    path = Path(state) / 'project-context.json'
    from beyin_v3_sync import atomic
    atomic(path, json.dumps({'schema': 1, 'enabled': bool(enabled)}))
    return bool(enabled)


def project_context(vault, state, project_id, project_name, budget=1200, today_iso=None):
    """Build scoped project context (latest receipt summary + due tasks).

    - Latest receipt for this project_id (max 600 chars).
    - Due tasks where due_at <= today, status active/waiting, visibility != private,
      and task.project matching project_name (casefold).
    - Other projects: count only, no titles.
    - Whole block capped at budget (default 1200 chars), cleanly omitting entries
      before the budget is exceeded without half-cut records.
    """
    if budget < 80 or not project_id:
        return ''
    from datetime import datetime, timezone
    from beyin_v3_sync import SyncEngine
    if today_iso is None:
        today_iso = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    engine = SyncEngine(vault, state)
    with engine.store._connect() as db:
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        latest_summary = None
        if 'receipt_checkpoints' in tables and 'receipts' in tables:
            matching_sessions = {row[0] for row in db.execute(
                'SELECT session FROM receipt_checkpoints WHERE project_id=?', (project_id,)
            )}
            if matching_sessions:
                candidates = []
                for (payload_str,) in db.execute('SELECT payload FROM receipts'):
                    try:
                        receipt = json.loads(payload_str)
                        if receipt.get('session') in matching_sessions and receipt.get('visibility') != 'private':
                            created_at = receipt.get('created_at')
                            summary = receipt.get('summary')
                            if created_at and summary:
                                candidates.append((created_at, summary))
                    except Exception:
                        continue
                if candidates:
                    candidates.sort(key=lambda item: item[0], reverse=True)
                    latest_summary = candidates[0][1][:600].strip()

        current_tasks = []
        other_due_count = 0
        norm_current_project = project_name.strip().casefold() if project_name else ''

        if 'records' in tables:
            for (payload_str,) in db.execute('SELECT payload FROM records'):
                try:
                    rec = json.loads(payload_str)
                    if rec.get('kind') != 'task':
                        continue
                    if rec.get('visibility') == 'private':
                        continue
                    if rec.get('status') not in ('active', 'waiting'):
                        continue
                    due_at = rec.get('due_at')
                    if not due_at or str(due_at)[:10] > str(today_iso)[:10]:
                        continue
                    task_proj = (rec.get('project') or '').strip().casefold()
                    if task_proj and norm_current_project and task_proj == norm_current_project:
                        title = (rec.get('title') or '').strip()
                        next_act = (rec.get('next_action') or '').strip()
                        if title:
                            current_tasks.append((title, next_act))
                    else:
                        other_due_count += 1
                except Exception:
                    continue

    if not latest_summary and not current_tasks and other_due_count == 0:
        return ''

    lines = [f'Project context ({project_name}):']
    if latest_summary:
        lines.append(f'Son kayit: {latest_summary}')
    if current_tasks:
        lines.append('Tarihi gelen gorevler:')
        for title, next_act in current_tasks:
            task_line = f'- {title}: {next_act}' if next_act else f'- {title}'
            lines.append(task_line)
    if other_due_count > 0:
        lines.append(f'(baska projelerde {other_due_count} tarihi gelmis gorev)')

    assembled = []
    current_len = 0
    for line in lines:
        added_len = len(line) + (1 if assembled else 0)
        if current_len + added_len > budget:
            break
        assembled.append(line)
        current_len += added_len

    if len(assembled) <= 1:
        return ''
    return '\n'.join(assembled)


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
        if event not in events or payload.get('no_memory') is True or os.environ.get('BEYIN_V3_INTERNAL') or os.environ.get('BEYIN_V3_SKIP') == '1':
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
        if read_project_context(state):
            proj_info = origin(payload, args.harness)
            rem_budget = min(1200, max(0, args.context_chars - len(text) - 2))
            extra = project_context(vault, state, proj_info.get('project_id', ''), proj_info.get('project', ''), budget=rem_budget)
            if extra:
                text = text + '\n\n' + extra
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
