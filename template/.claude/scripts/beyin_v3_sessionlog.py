"""Daily session log under ``daily/log/`` — facts by mechanism, summary by discipline.

The hook writes a deterministic per-session block at SessionStart and closes it at
SessionEnd (times, harness, prompt count, receipt references). The session's own
agent fills the ``### Özet`` section from the one-line SessionStart reminder; this
module never rewrites that section and never calls a model. Opt-in through the
``daily_log`` preference; when it is off nothing here runs and nothing is injected.
Design and rejected alternatives: docs/specs/2026-09-26-daily-log-design.md.
"""
import contextlib
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time

import _portalock

ABANDONED_AFTER_SECONDS = 8 * 3600  # an open session older than this is dead
REMINDER = ('Günlük log: oturum bitmeden daily/log bloğundaki Özet bölümünü beş bölümle '
            'doldur (Bağlam / Önemli Konuşmalar / Alınan Kararlar / Öğrenilenler / '
            'Yapılacaklar; karar, tercih, sonuç ve açık işler kalır, araç çağrısı ve '
            'tekrar çıkar). Kalıcı değer yoksa boş bırak.')
FRONTMATTER = json.dumps({'kind': 'note', 'type': 'episodic', 'visibility': 'internal'},
                         ensure_ascii=False)


def _key(session_id):
    return hashlib.sha256(str(session_id).encode()).hexdigest()[:24]


def _hm(epoch):
    return dt.datetime.fromtimestamp(epoch).strftime('%H:%M')


def _day(epoch):
    return dt.datetime.fromtimestamp(epoch).date().isoformat()


def _log_path(vault, day):
    return Path(vault) / 'daily' / 'log' / f'{day}.md'


@contextlib.contextmanager
def _locked(state):
    handle = open(Path(state) / 'daily-log.lock', 'a+b')
    try:
        with _portalock.exclusive(handle):
            yield
    finally:
        handle.close()


def _atomic(path, text):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(text, encoding='utf-8')
    os.replace(tmp, path)


def _ensure_day_file(vault, day):
    path = _log_path(vault, day)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic(path, '---\n' + FRONTMATTER + '\n---\n# Günlük oturum günlüğü\n\n')
    return path


def _marker(key):
    return f'<!-- beyin-session:{key} -->'


def _read_start(state, key):
    try:
        return float((Path(state) / f'sessionlog_start.{key}').read_text().strip())
    except (OSError, ValueError):
        return None


def _mark_abandoned(state, vault, now):
    """A session whose start state outlived the TTL never saw SessionEnd; mark its
    open block so the next boot explains the gap instead of silently keeping OPEN."""
    for state_file in Path(state).glob('sessionlog_start.*'):
        key = state_file.name.removeprefix('sessionlog_start.')
        started = _read_start(state, key)
        if started is None or now - started <= ABANDONED_AFTER_SECONDS:
            continue
        marker = _marker(key)
        for day in sorted(_day(started + n * 86400) for n in range(0, 4)):
            path = _log_path(vault, day)
            if not path.exists() or marker not in path.read_text(encoding='utf-8'):
                continue
            lines = path.read_text(encoding='utf-8').split('\n')
            for index, line in enumerate(lines):
                if line == marker and index + 1 < len(lines) and lines[index + 1].startswith('## OPEN ·'):
                    lines[index + 1] = lines[index + 1].replace('## OPEN ·', '## OPEN (yarıda kaldı) ·', 1)
            _atomic(path, '\n'.join(lines))
        state_file.unlink(missing_ok=True)


def _receipt_lines(vault, state, started, now):
    database = Path(state) / 'memory.sqlite3'
    if not database.exists():
        return []
    # Receipts carry a UTC created_at; compare aware datetimes, not clock-local strings.
    start_dt = dt.datetime.fromtimestamp(started, dt.timezone.utc)
    end_dt = dt.datetime.fromtimestamp(now, dt.timezone.utc)
    lines = []
    with contextlib.closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True)) as db:
        for receipt_id, payload in db.execute('SELECT id, payload FROM receipts ORDER BY id').fetchall():
            try:
                event = json.loads(payload)
                created = dt.datetime.fromisoformat(event.get('created_at'))
            except (TypeError, ValueError):
                continue
            if created.tzinfo is None:
                created = created.replace(tzinfo=dt.timezone.utc)
            if start_dt <= created <= end_dt:
                summary = str(event.get('summary', '')).replace('\n', ' ')
                source = hashlib.sha256(str(receipt_id).encode()).hexdigest()
                lines.append(f'- receipt: {summary} → receipts/{source}.md')
    return lines


def session_start(vault, state, settings, harness, session_id, now=None):
    """Open (or reuse) today's block for this session; returns the reminder line or None."""
    if not settings.get('daily_log'):
        return None
    now = now if now is not None else time.time()
    key = _key(session_id)
    with _locked(state):
        _mark_abandoned(state, vault, now)
        path = _ensure_day_file(vault, _day(now))
        (Path(state) / f'sessionlog_start.{key}').write_text(str(now))
        text = path.read_text(encoding='utf-8')
        marker = _marker(key)
        if marker not in text:
            block = marker + f'\n## OPEN · {_hm(now)} · {harness}\n### Özet\n\n'
            _atomic(path, text.rstrip('\n') + '\n\n' + block)
    return REMINDER


def session_end(vault, state, settings, harness, session_id, now=None):
    """Close the session's block: span, prompt count, receipts, reflection note.
    The agent-written Özet body is never touched."""
    if not settings.get('daily_log'):
        return
    now = now if now is not None else time.time()
    key = _key(session_id)
    with _locked(state):
        started = _read_start(state, key)
        (Path(state) / f'sessionlog_start.{key}').unlink(missing_ok=True)
        if started is None or started > now:
            return
        marker = _marker(key)
        path = _log_path(vault, _day(started))
        if not path.exists() or marker not in path.read_text(encoding='utf-8'):
            return
        text = path.read_text(encoding='utf-8')
        lines = text.split('\n')
        index = lines.index(marker)
        header = lines[index + 1] if index + 1 < len(lines) else ''
        if not header.startswith('## OPEN ·'):
            return
        try:
            count = int((Path(state) / f'prompt_count.{key}').read_text().strip())
            span = f'## {_hm(started)}–{_hm(now)} · {harness} · {count} istem'
        except (OSError, ValueError):
            span = f'## {_hm(started)}–{_hm(now)} · {harness}'
        details = _receipt_lines(vault, state, started, now)
        if (Path(state) / f'needs_reflection.{key}').exists():
            details.append('- reflection: son promptlar hafıza güncellenmeden geçti')
        lines[index + 1] = span + ('\n' + '\n'.join(details) if details else '')
        _atomic(path, '\n'.join(lines))
