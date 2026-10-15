"""Session-scoped context deduplication (#363): prevent re-injecting already delivered records.

Each session tracks delivered records under `<state>/session-delivery/`, named by the hash
of harness and session id. The file holds only `{version, harness, session, at, records: {id: source_sha256}}`.
A record is considered a duplicate only if both its id and its source_sha256 match a previously delivered
record in the active session. If the source file was edited on disk, its sha256 changes and the note
is treated as novel and delivered.

The toggle lives in `<state>/context-dedupe.json` (default off), never in `.beyin-preferences.json`:
an older release rejects unknown preference keys, so a rollback would break its doctor and hooks.
Every function here fails open: any error in reading or writing the ledger returns all records as novel.
The session ledger is cleared on compaction (PreCompact or SessionStart with source: compact) and on SessionEnd.
"""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

SETTINGS_FILE = 'context-dedupe.json'
DELIVERY_DIR = 'session-delivery'
MAX_SESSIONS = 128
MAX_AGE_SECONDS = 24 * 3600
MAX_FILE_BYTES = 65536


def _session_file(state, harness, session, create=False):
    if not isinstance(session, str) or not session or session == 'unknown' or len(session) > 512:
        return None
    folder = Path(state) / DELIVERY_DIR
    if folder.is_symlink():
        return None
    if create:
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    digest = hashlib.sha256((str(harness) + '\0' + session).encode('utf-8')).hexdigest()
    path = folder / (digest + '.json')
    return None if path.is_symlink() else path


def read_settings(state):
    """Return (enabled, valid). Missing file: off and valid. Damaged file: off and invalid."""
    if os.environ.get('BEYIN_V3_CONTEXT_DEDUPE') == '1':
        return True, True
    path = Path(state) / SETTINGS_FILE
    if not path.exists() and not path.is_symlink():
        return False, True
    try:
        if path.is_symlink():
            raise ValueError('symlink')
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or set(data) - {'schema', 'enabled'} or data.get('schema', 1) != 1 \
                or type(data.get('enabled')) is not bool:
            raise ValueError('shape')
        return data['enabled'], True
    except (ValueError, OSError):
        return False, False


def save_settings(state, enabled):
    """Atomically persist enabled setting."""
    if type(enabled) is not bool:
        raise ValueError('enabled must be boolean')
    path = Path(state) / SETTINGS_FILE
    folder = path.parent
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = {'schema': 1, 'enabled': enabled}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=folder, delete=False) as handle:
            temporary = handle.name
            os.chmod(temporary, 0o600)
            json.dump(data, handle)
            handle.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass


def is_enabled(state):
    """Convenience predicate for hook fastpath."""
    enabled, _ = read_settings(state)
    return enabled


def _read_ledger(path, now=None):
    try:
        if path is None or not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
            return {}
        now = time.time() if now is None else now
        value = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(value, dict) or value.get('version') != 1:
            return {}
        at = value.get('at')
        if type(at) not in (int, float) or not 0 <= now - at < MAX_AGE_SECONDS:
            return {}
        records = value.get('records')
        if not isinstance(records, dict):
            return {}
        return records
    except (OSError, ValueError):
        return {}


def filter_novel(state, harness, session, records, now=None):
    """Separate records into (novel, duplicates).

    A record is a duplicate only if both its id and its source_sha256 were already recorded
    in this session's delivery ledger. Fail open: on any error, all records are novel.
    """
    if not records:
        return [], []
    if not is_enabled(state):
        return list(records), []
    path = _session_file(state, harness, session)
    if path is None:
        return list(records), []
    delivered = _read_ledger(path, now=now)
    if not delivered:
        return list(records), []
    novel, duplicates = [], []
    for r in records:
        if not isinstance(r, dict):
            novel.append(r)
            continue
        rid = r.get('id')
        sha = r.get('source_sha256')
        if rid and sha and delivered.get(rid) == sha:
            duplicates.append(r)
        else:
            novel.append(r)
    return novel, duplicates


def record_delivered(state, harness, session, records, now=None):
    """Update the session delivery ledger with newly delivered records. Fail open."""
    if not records:
        return
    if not is_enabled(state):
        return
    now = time.time() if now is None else now
    path = _session_file(state, harness, session, create=True)
    if path is None:
        return
    existing = _read_ledger(path, now=now)
    updates = {r['id']: r['source_sha256'] for r in records
               if isinstance(r, dict) and r.get('id') and r.get('source_sha256')}
    if not updates:
        return
    existing.update(updates)
    payload = {
        'version': 1,
        'harness': harness,
        'session': session,
        'at': now,
        'records': existing,
    }
    temporary = None
    try:
        parent = path.parent
        files = sorted((p for p in parent.glob('*.json') if not p.is_symlink() and p != path),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for candidate in files[MAX_SESSIONS - 1:]:
            candidate.unlink(missing_ok=True)
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=parent, delete=False) as handle:
            temporary = handle.name
            os.chmod(temporary, 0o600)
            json.dump(payload, handle)
            handle.write('\n')
        os.replace(temporary, path)
    except (OSError, ValueError):
        pass
    finally:
        if temporary and os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass


def reset_session(state, harness, session):
    """Remove the delivery ledger for a session (e.g. on compaction or session end)."""
    try:
        path = _session_file(state, harness, session)
        if path is not None and path.is_file():
            path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def doctor(state):
    """Read-only: status of the dedupe toggle and number of cached session delivery ledgers."""
    value, valid = read_settings(state)
    result = {'enabled': value, 'valid': valid, 'sessions': 0}
    folder = Path(state) / DELIVERY_DIR
    if folder.is_dir() and not folder.is_symlink():
        try:
            with os.scandir(folder) as listing:
                result['sessions'] = sum(1 for e in listing if e.name.endswith('.json') and not e.is_symlink())
        except OSError:
            pass
    return result
