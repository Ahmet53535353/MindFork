"""Deterministic receipt indexes; never rewrite existing human daily/knowledge."""
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
import time


def _checkpoint_schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS receipt_checkpoints(harness TEXT, session TEXT, at REAL, turn_at REAL DEFAULT 0, PRIMARY KEY(harness,session))')
    if 'turn_at' not in {row[1] for row in db.execute('PRAGMA table_info(receipt_checkpoints)')}:
        db.execute('ALTER TABLE receipt_checkpoints ADD COLUMN turn_at REAL DEFAULT 0')
    if 'unattended' not in {row[1] for row in db.execute('PRAGMA table_info(receipt_checkpoints)')}:
        db.execute('ALTER TABLE receipt_checkpoints ADD COLUMN unattended INTEGER DEFAULT 0')
    for column in ('project', 'project_id'):
        if column not in {row[1] for row in db.execute('PRAGMA table_info(receipt_checkpoints)')}:
            db.execute(f'ALTER TABLE receipt_checkpoints ADD COLUMN {column} TEXT')


def record_checkpoints(engine, events):
    with engine.store._connect() as db:
        _checkpoint_schema(db)
        for event in sorted(events, key=lambda item: item.get('at', 0)):
            if not event.get('session') or event.get('no_memory'):
                continue
            is_unattended = 1 if event.get('unattended') else 0
            if event.get('event') in ('SessionStart', 'UserPromptSubmit'):
                values = (event['harness'], event['session'], event['at'], is_unattended)
                db.execute('INSERT INTO receipt_checkpoints(harness,session,at,turn_at,unattended) VALUES (?,?,0,?,?) ON CONFLICT(harness,session) DO UPDATE SET turn_at=MAX(turn_at,excluded.turn_at), unattended=MAX(unattended,excluded.unattended)', values)
            elif event.get('event') in ('Stop', 'SessionEnd'):
                values = (event['harness'], event['session'], event['at'], is_unattended)
                db.execute('INSERT INTO receipt_checkpoints(harness,session,at,unattended) VALUES (?,?,?,?) ON CONFLICT(harness,session) DO UPDATE SET at=MAX(at,excluded.at), unattended=MAX(unattended,excluded.unattended)', values)
            if event.get('project') and event.get('project_id'):
                db.execute('UPDATE receipt_checkpoints SET project=?,project_id=? WHERE harness=? AND session=?',
                           (event['project'], event['project_id'], event['harness'], event['session']))


def refresh_gaps(engine, db):
    atomic = engine.projection_helpers()[1]
    _checkpoint_schema(db)
    receipts = [json.loads(row[0]) for row in db.execute('SELECT payload FROM receipts')]
    now = time.time()
    seven_days = now - 7 * 86400
    thirty_days = now - 30 * 86400

    gaps = []
    unattended_count = 0
    windows = {
        'all_time': {'total': 0, 'covered': 0, 'missing': 0},
        'last_7d': {'total': 0, 'covered': 0, 'missing': 0},
        'last_30d': {'total': 0, 'covered': 0, 'missing': 0},
    }

    for row in db.execute('SELECT harness,session,at,turn_at,project,project_id,unattended FROM receipt_checkpoints'):
        if not row[2] or row[2] < row[3]:
            continue
        is_unattended = bool(row[6])
        if is_unattended:
            unattended_count += 1
            continue

        chk_at = row[2]
        threshold = row[3] or row[2]
        matched = any(r.get('harness') == row[0] and r.get('session') == row[1] and
                      datetime.fromisoformat(r.get('created_at', '1970-01-01T00:00:00+00:00')).timestamp() >= threshold for r in receipts)

        for w_name, w_active in (('all_time', True), ('last_30d', chk_at >= thirty_days), ('last_7d', chk_at >= seven_days)):
            if w_active:
                windows[w_name]['total'] += 1
                if matched:
                    windows[w_name]['covered'] += 1
                else:
                    windows[w_name]['missing'] += 1

        if not matched:
            gaps.append({'harness': row[0], 'session': row[1], 'checkpoint_at': row[2], 'turn_at': row[3], 'scope': 'session_only' if row[0] == 'antigravity' else 'turn' if row[3] else 'terminal_only'})
            if row[4] and row[5]:
                gaps[-1].update(project=row[4], project_id=row[5])

    coverage = {
        'ratio': round(windows['all_time']['covered'] / windows['all_time']['total'], 3) if windows['all_time']['total'] else None,
        'covered': windows['all_time']['covered'],
        'total': windows['all_time']['total'],
        'missing': windows['all_time']['missing'],
        'last_7d': {
            'ratio': round(windows['last_7d']['covered'] / windows['last_7d']['total'], 3) if windows['last_7d']['total'] else None,
            'covered': windows['last_7d']['covered'],
            'total': windows['last_7d']['total'],
            'missing': windows['last_7d']['missing'],
        },
        'last_30d': {
            'ratio': round(windows['last_30d']['covered'] / windows['last_30d']['total'], 3) if windows['last_30d']['total'] else None,
            'covered': windows['last_30d']['covered'],
            'total': windows['last_30d']['total'],
            'missing': windows['last_30d']['missing'],
        }
    }

    atomic(engine.state/'receipt-gaps.json', json.dumps({
        'potential_missing_receipts': len(gaps),
        'unattended_checkpoints': unattended_count,
        'receipt_coverage': coverage,
        'checkpoints': gaps,
        'scope_limits': {'antigravity': 'session_only; later per-turn boundaries unsupported', 'missing_prompt_event': 'terminal_only; receipt attribution may be incomplete'},
        'meaning': 'Checkpoint without a matching structured receipt; may be trivial or deliberately omitted. No summary inferred.'
    }))


def project_receipts(engine, db):
    _hash, atomic, render = engine.projection_helpers()
    db.execute('CREATE TABLE IF NOT EXISTS receipt_views(path TEXT PRIMARY KEY, hash TEXT NOT NULL)')
    migration = engine.state/'v2-migration.json'
    previous = json.loads(migration.read_text(encoding='utf-8')) if migration.exists() else {}
    historical = set(previous.get('historical_receipts', []))
    grouped = defaultdict(list)
    for row in db.execute('SELECT payload FROM receipts ORDER BY id'):
        event = json.loads(row[0])
        source = 'receipts/' + _hash(event['event_id']) + '.md'
        if source in historical or not event.get('created_at'):
            continue
        date = event['created_at'][:10]
        grouped[date].append((event['created_at'], source, event['summary']))
    desired = {}
    outcomes = []
    for day, items in sorted(grouped.items()):
        entries = []
        for at, source, summary in sorted(items):
            entries.append(f'## {at}\n\n{summary}\n\nSource: [[{source}]]\n')
            outcomes.append(f'- {day}: {summary}\n  Source: [[{source}]]\n')
        desired[f'daily/v3/{day}.md'] = render({'generated': True, 'kind': 'receipt-index'}, '# Recorded outcomes\n\nAgent-authored claims, not independently verified facts.\n\n'+'\n'.join(entries))
    if outcomes:
        desired['knowledge/v3/outcomes.md'] = render({'generated': True, 'kind': 'receipt-index'}, '# Outcome source index\n\nThis index links semantic receipts. It is not an automatic knowledge compiler.\n\n'+''.join(outcomes))
    conflicts = []
    for relative, content in desired.items():
        path = engine._path(relative)
        old = _hash(path.read_bytes()) if path.exists() else None
        desired_hash = _hash(content)
        tracked = db.execute('SELECT hash FROM receipt_views WHERE path=?', (relative,)).fetchone()
        if old != desired_hash and old is not None and (not tracked or old != tracked[0]):
            conflicts.append({'source': relative, 'reason': 'manual receipt view edit preserved'})
            continue
        if old != desired_hash:
            # Recheck immediately before atomic replacement; remote writers still require reconciliation.
            if (_hash(path.read_bytes()) if path.exists() else None) != old:
                conflicts.append({'source': relative, 'reason': 'receipt view changed during projection'})
                continue
            atomic(path, content)
        db.execute('INSERT OR REPLACE INTO receipt_views VALUES (?,?)', (relative, desired_hash))
    refresh_gaps(engine, db)
    return conflicts
