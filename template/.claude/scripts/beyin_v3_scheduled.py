"""scheduled-check (#267): sync then doctor for an OS scheduler the user sets up themselves.

No model call, no service installed, nothing repaired. Everything this writes lives in the
machine-local runtime state, never in the vault: a record synced through git or iCloud would
reach another machine whose health it does not describe. Files:

- `scheduled-check.json`: the last run (status, issue kinds with counts, notification bookkeeping).
- `scheduled-check.lock`: an OS advisory lock, released by the OS when the run ends or dies, so
  there is no stale lock to reclaim. The file stays; unlinking a held advisory-lock file lets a
  later run lock a new inode while the first still owns the old one (beyin_v3_compact).
- `scheduled-notice.json`: one line for the next session start, written only when an opt-in
  notification could not be shown; the first session that claims it says it, once.

The notification is opt-in (`scheduled-check --notify`) and uses only what the platform ships:
PowerShell toast on Windows, osascript on macOS, notify-send on Linux. It fires on a state change
(healthy -> needs attention, needs attention -> healthy) and, while a problem lasts, once more
every REMIND_SECONDS. Its text names issue kinds and counts only, never a note title or path:
the corner of a shared screen is not a private place.
"""
import calendar
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time

RECORD_FILE = 'scheduled-check.json'
LOCK_FILE = 'scheduled-check.lock'
NOTICE_FILE = 'scheduled-notice.json'
REMIND_SECONDS = 7 * 86400
STEP_TIMEOUT = 900
NOTIFY_TIMEOUT = 30
MAX_FILE_BYTES = 16384
TITLE = 'Avenox Beyin'
# 0 ok, 1 the check itself failed, 3 another run holds the lock, 4 needs attention.
# 2 stays argparse's usage error: a typo in the scheduler command must never read as "attention".
EXIT_CODES = {'ok': 0, 'error': 1, 'already_running': 3, 'needs_attention': 4}
STATUSES = ('ok', 'needs_attention', 'error')
ISSUE_LABELS = (('sync_conflict', 'sync cakismasi'), ('sync_degraded', 'sync uyarisi'),
                ('hook', 'hook uyarisi'), ('skill_or_instruction', 'skill/talimat cakismasi'),
                ('task', 'gorev kaydi sorunu'), ('validity', 'gecerlilik sorunu'))
ISSUE_KINDS = tuple(kind for kind, _ in ISSUE_LABELS)
DELIVERIES = ('shown', 'failed', 'unavailable')


def _utc(seconds):
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(seconds))


def _seconds(text):
    return calendar.timegm(time.strptime(text, '%Y-%m-%dT%H:%M:%SZ'))


def _read(path):
    """A small JSON object from the state, or None when it is missing or unusable."""
    path = Path(path)
    try:
        if path.is_symlink() or not path.is_file():
            return None
        with path.open('rb') as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            return None
        value = json.loads(data.decode('utf-8'))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _write(path, value):
    path = Path(path)
    if path.is_symlink():
        raise OSError(path.name + ' must be a regular file')
    fd, temporary = tempfile.mkstemp(prefix='.scheduled-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(value, out, ensure_ascii=True, indent=2)
            out.write('\n'); out.flush(); os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _lock(handle):
    """True when this process now holds the run lock; False when another run holds it."""
    try:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def issues(sync_result, doctor_result):
    """{kind: count} from the sync and doctor JSON; kinds and numbers only, never a path."""
    found = {}
    sync_status = sync_result.get('status')
    if sync_status == 'conflict':
        found['sync_conflict'] = max(1, len(sync_result.get('conflicts') or []))
    elif sync_status == 'degraded':
        found['sync_degraded'] = max(1, len(sync_result.get('warnings') or []))
    if (doctor_result.get('hook_paths') or {}).get('status') == 'stale' or doctor_result.get('hook-error.json'):
        found['hook'] = 1
    count = len(doctor_result.get('skill_conflicts') or []) + len(doctor_result.get('instruction_conflicts') or [])
    if count:
        found['skill_or_instruction'] = count
    for kind, key, value in (('task', 'task_completion', 'strict_issue_count'),
                             ('validity', 'validity', 'ignored_rejection_count')):
        report = doctor_result.get(key) or {}
        count = (report.get(value) or 0) + (1 if report.get('error') else 0)
        if count:
            found[kind] = count
    return found


def message(status, found, reminder=False):
    """The notification text: issue kinds and counts, never a note title or a path."""
    if status == 'ok':
        return 'Beyin: sorunlar giderildi, kasa saglikli.'
    parts = [label + ' (' + str(found[kind]) + ')' for kind, label in ISSUE_LABELS if kind in found]
    return ('Beyin' + (' (hatirlatma)' if reminder else '') + ': ' +
            (', '.join(parts) or 'kontrol gerektiren bir sorun') + ' - ayrinti: beyin.py doctor')


def notify_command(text, platform=None):
    """(argv, extra environment) for the platform's own notifier, or None when there is none."""
    platform = sys.platform if platform is None else platform
    if platform == 'win32':
        # Windows PowerShell 5.1 ships with every supported Windows and still projects WinRT;
        # the text travels in the environment, so nothing in it is parsed as script.
        script = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null\n"
                  "$xml = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)\n"
                  "$text = $xml.GetElementsByTagName('text')\n"
                  "$text.Item(0).AppendChild($xml.CreateTextNode($env:BEYIN_NOTIFY_TITLE)) > $null\n"
                  "$text.Item(1).AppendChild($xml.CreateTextNode($env:BEYIN_NOTIFY_TEXT)) > $null\n"
                  "$app = '{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe'\n"
                  "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app).Show("
                  "[Windows.UI.Notifications.ToastNotification]::new($xml))\n")
        root = os.environ.get('SystemRoot') or os.environ.get('SYSTEMROOT') or r'C:\Windows'
        executable = os.path.join(root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
        return ([executable, '-NoProfile', '-NonInteractive', '-Command', script],
                {'BEYIN_NOTIFY_TITLE': TITLE, 'BEYIN_NOTIFY_TEXT': text})
    if platform == 'darwin':
        return (['/usr/bin/osascript', '-e', 'on run argv', '-e',
                 'display notification (item 2 of argv) with title (item 1 of argv)', '-e', 'end run', TITLE, text], {})
    executable = shutil.which('notify-send')
    if executable is None:
        return None
    return [executable, '--app-name=' + TITLE, TITLE, text], {}


def show(text, platform=None):
    """'shown', 'failed' (the notifier ran and refused) or 'unavailable' (no notifier here)."""
    command = notify_command(text, platform)
    if command is None:
        return 'unavailable'
    argv, extra = command
    options = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL,
               'timeout': NOTIFY_TIMEOUT, 'env': dict(os.environ, **extra)}
    if os.name == 'nt':
        options['creationflags'] = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    try:
        return 'shown' if subprocess.run(argv, **options).returncode == 0 else 'failed'
    except FileNotFoundError:
        return 'unavailable'
    except (OSError, subprocess.SubprocessError):
        return 'failed'


def decide(previous, status, now):
    """(text or None, reminder): what to tell the user for this run, given the last record.

    The last status the user was told about starts as healthy, so a first run that finds a
    problem says so and a first healthy run stays quiet. A failed check changes nothing.
    """
    told = previous.get('notified_status') if previous.get('notified_status') in STATUSES else 'ok'
    last = previous.get('last_notified_at')
    try:
        since = now - _seconds(last) if isinstance(last, str) else None
    except ValueError:
        since = None
    if status == 'needs_attention':
        if told != 'needs_attention':
            return 'attention', False
        if since is None or not 0 <= since < REMIND_SECONDS:
            return 'attention', True
    elif status == 'ok' and told == 'needs_attention':
        return 'recovered', False
    return None, False


def run(vault, state, cli, notify=False, now=None, display=None):
    """(record, exit code). Runs `sync` then `doctor` as child processes of the same CLI, so the
    report is exactly what `doctor` prints by hand; the record goes to the runtime state."""
    state = Path(state)
    state.mkdir(parents=True, exist_ok=True)
    lock = state / LOCK_FILE
    if lock.is_symlink():
        raise OSError(LOCK_FILE + ' must be a regular file')
    with lock.open('a+b') as handle:
        if not _lock(handle):
            return {'status': 'already_running'}, EXIT_CODES['already_running']
        started = time.time() if now is None else now
        previous = _read(state / RECORD_FILE) or {}
        record = {'schema': 1, 'started_at': _utc(started)}
        try:
            outputs = {}
            for command in ('sync', 'doctor'):
                ran = subprocess.run([sys.executable, str(cli), '--vault', str(vault), '--state', str(state), command],
                                     capture_output=True, text=True, encoding='utf-8', timeout=STEP_TIMEOUT,
                                     stdin=subprocess.DEVNULL)
                if ran.returncode:
                    raise RuntimeError(command + ' exited ' + str(ran.returncode))
                outputs[command] = json.loads(ran.stdout)
            record['sync_status'] = outputs['sync'].get('status')
            record['doctor_status'] = outputs['doctor'].get('status')
            record['issues'] = issues(outputs['sync'], outputs['doctor'])
            attention = record['doctor_status'] == 'needs_attention' or bool(record['issues'])
            record['status'] = 'needs_attention' if attention else 'ok'
        except Exception as exc:  # the record says why; a failed check is never reported as healthy
            record['status'] = 'error'
            # The type only: a child's message can quote a note path.
            record['error'] = type(exc).__name__
        record['finished_at'] = _utc(time.time() if now is None else now)
        for key in ('notified_status', 'last_notified_at'):
            if key in previous:
                record[key] = previous[key]
        record['notify'] = bool(notify)
        if notify:
            kind, reminder = decide(previous, record['status'], started)
            if kind:
                text = message(record['status'], record.get('issues', {}), reminder)
                delivery = (display or show)(text)
                record['notification'] = delivery if delivery in DELIVERIES else 'failed'
                record['notified_status'] = record['status']
                record['last_notified_at'] = record['finished_at']
                if record['notification'] == 'shown':
                    (state / NOTICE_FILE).unlink(missing_ok=True)
                else:
                    _write(state / NOTICE_FILE, {'schema': 1, 'at': record['finished_at'], 'text': text})
        _write(state / RECORD_FILE, record)
        return record, EXIT_CODES[record['status']]


def doctor(state, now=None):
    """The last run for doctor, with its age. Only known fields of known types pass: the file
    is in the user's state folder and a hand edit must not inject text into doctor."""
    path = Path(state) / RECORD_FILE
    if not path.exists() and not path.is_symlink():
        return {'status': 'never_run'}
    record = _read(path)
    try:
        if record is None or record.get('status') not in STATUSES:
            raise ValueError('shape')
        finished = _seconds(record['finished_at'])
        shown = {'status': record['status'], 'finished_at': record['finished_at'],
                 'age_hours': max(0, int(((time.time() if now is None else now) - finished) // 3600)),
                 'notify': record.get('notify') is True}
    except (ValueError, KeyError, TypeError):
        return {'status': 'unreadable'}
    found = record.get('issues')
    if isinstance(found, dict):
        shown['issues'] = {kind: count for kind, count in found.items()
                           if kind in ISSUE_KINDS and type(count) is int and 0 < count < 10 ** 6}
    if record.get('error') in ('RuntimeError', 'ValueError', 'TimeoutExpired', 'OSError', 'JSONDecodeError'):
        shown['error'] = record['error']
    elif record['status'] == 'error':
        shown['error'] = 'other'
    if record.get('notification') in DELIVERIES:
        shown['notification'] = record['notification']
    last = record.get('last_notified_at')
    if isinstance(last, str):
        try:
            _seconds(last)
            shown['last_notified_at'] = last
        except ValueError:
            pass
    return shown


def session_notice(state):
    """The line for a notification that could not be shown; said by one session, once.

    The notice is claimed by renaming it first, so two sessions opening together cannot both
    print it. Only a text this module wrote passes (ASCII, one line, bounded)."""
    path = Path(state) / NOTICE_FILE
    claimed = Path(state) / ('.scheduled-notice-' + str(os.getpid()) + '-' + str(time.monotonic_ns()))
    try:
        if path.is_symlink():
            return ''
        os.replace(path, claimed)
    except OSError:
        return ''
    try:
        value = _read(claimed) or {}
    finally:
        claimed.unlink(missing_ok=True)
    text = value.get('text')
    if not isinstance(text, str) or not text.startswith('Beyin') or len(text) > 300 \
            or not text.isascii() or '\n' in text or '\r' in text:
        return ''
    return 'Zamanlanmis denetim bildirimi gosterilemedi; kullaniciya soyle: ' + text + '\n'
