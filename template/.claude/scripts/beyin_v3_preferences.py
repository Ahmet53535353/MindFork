"""User-owned, portable controls for local checks and automatic context. No models."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import time

PROFILES = {
    # The released 3.5.1 schema, key for key. A key outside it is not a preference: it is
    # a file an older build refuses to validate, and after a rollback that refusal takes
    # doctor, preferences and the SessionStart hook down with it (upstream hit this with the
    # hygiene opt-ins, #132). Opt-ins therefore live in the runtime state, not here.
    'normal': dict(auto_sync=True, interval_minutes=0, context_mode='turn', context_chars=5000, secret_filter=False),
    'economical': dict(auto_sync=True, interval_minutes=15, context_mode='session', context_chars=2000, secret_filter=False),
    'manual': dict(auto_sync=False, interval_minutes=15, context_mode='off', context_chars=2000, secret_filter=False),
}
# The daily log is on by default: it is the most visible way the system remembers a session,
# and while it defaulted off nobody could discover it existed. Users who never state a choice
# get one SessionStart line naming the opt-out, then silence
# (docs/specs/2026-09-26-followup-findings-plan.md).
def validate(value):
    if not isinstance(value, dict) or set(value) - set(PROFILES['normal']):
        raise ValueError('Unsupported preferences; use beyin.py preferences')
    result = dict(PROFILES['normal'], **{key: item for key, item in value.items() if key in PROFILES['normal']})
    if type(result['auto_sync']) is not bool:
        raise ValueError('auto_sync must be boolean')
    if type(result['secret_filter']) is not bool:
        raise ValueError('secret_filter must be boolean')
    for key, low, high in [('interval_minutes', 0, 1440), ('context_chars', 1000, 12000)]:
        if type(result[key]) is not int or not low <= result[key] <= high:
            raise ValueError(f'{key} must be an integer between {low} and {high}')
    if result['context_mode'] not in ('turn', 'session', 'off'):
        raise ValueError('context_mode must be turn, session or off')
    return result


def preferences_path(vault):
    path = Path(vault) / '.beyin-preferences.json'
    if path.is_symlink():
        raise ValueError('Preferences must be a regular vault-local file')
    return path


def read(vault):
    path = preferences_path(vault)
    return validate(json.loads(path.read_text(encoding='utf-8')) if path.exists() else {})

def save(vault, changes, profile=None):
    # Validate the existing file too: malformed user settings must not be overwritten.
    current = read(vault)
    # The secret filter is an independent safety choice; changing performance profiles must
    # not silently enable or disable it. The daily log is not here at all, so no key outside
    # the released schema is ever written back.
    base = dict(PROFILES[profile], secret_filter=current['secret_filter']) if profile else current
    result = validate(dict(base, **changes))
    path = preferences_path(vault)
    fd, temporary = tempfile.mkstemp(prefix='.beyin-preferences-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(result, out, ensure_ascii=False, indent=2)
            out.write('\n'); out.flush(); os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return result


def claim_check(state, settings, event, now=None):
    """Atomically rate-limit automatic launches, across clients, not manual CLI reads.

    A new session always refreshes. The interval is a minimum between subsequent
    event-triggered checks, never a timer or an always-on service.
    """
    if not settings['auto_sync']:
        return False
    if not settings['interval_minutes']:
        return True
    now = time.time() if now is None else now
    state = Path(state); state.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(state / 'check-cadence.sqlite3', timeout=1)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS cadence (id INTEGER PRIMARY KEY, started REAL)')
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT started FROM cadence WHERE id=1').fetchone()
        retry = (state / 'hook-error.json').exists()
        if event != 'SessionStart' and not retry and row and 0 <= now-row[0] < settings['interval_minutes']*60:
            return False
        db.execute('INSERT OR REPLACE INTO cadence VALUES (1, ?)', (now,))
    return True
