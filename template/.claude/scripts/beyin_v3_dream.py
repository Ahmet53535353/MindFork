"""AutoDream consolidation window, phase 1: gates plus a read-only measurement.

A window is never a background service. The user runs it, it reports, and a mutating
window (phase 2+) still requires the same three gates: 24 hours since the last window,
at least five new receipts since that window, and an exclusive lock. Phase 1 writes
nothing at all: no report file, no snapshot, no watermark, no index change. A dry run
that consumed the watermark would silence the very measurement week this phase exists for,
so the gates are computed and reported here and only a mutating window enforces them.

Spec: docs/specs/2026-09-26-autodream-lite-roadmap.md
"""
from __future__ import annotations

import datetime as dt
from fnmatch import fnmatch
import json
import re
import unicodedata
from pathlib import Path

import _portalock
import beyin_v3_projections as projections

MIN_HOURS = 24
MIN_RECEIPTS = 5
STALE_DAYS = 90
NOTE_CAP_CHARS = 12000
NOTE_TREES = ('knowledge', 'notes')
# Generated and human index files carry the same size discipline as single notes; the
# budgets are checked here and reported, never enforced by rewriting the file.
SIZE_CHECKED = ('knowledge/index.md', 'knowledge/log.md', 'knowledge/v3/outcomes.md')
GENERATED_GLOBS = ('daily/v3/*.md',)


def is_generated(relative):
    """One source of truth with the projection writer: views the engine rewrites itself."""
    return (relative.startswith('knowledge/v3/')
            or relative in projections.PROJECTION_GUARD
            or any(fnmatch(relative, pattern) for pattern in GENERATED_GLOBS))
PRUNE_MARKER = 'draft'


def _now(now=None):
    return (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)


def _parse(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        moment = dt.datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return moment.replace(tzinfo=dt.timezone.utc) if moment.tzinfo is None else moment


def _locked(state):
    # A report must not even create its lock file: an absent lock cannot be held. The
    # check-then-acquire race only affects the reported status of a read-only window.
    path = Path(state) / 'dream.lock'
    if not path.exists():
        return False
    handle = open(path, 'a+b')
    try:
        with _portalock.exclusive(handle, blocking=False) as acquired:
            return not acquired
    finally:
        handle.close()


def gate_status(vault, state, store, now=None, min_hours=MIN_HOURS, min_receipts=MIN_RECEIPTS):
    last_run = _parse(store.read_meta('dream.last_run'))
    moment = _now(now)
    stats = store.receipt_stats(since=last_run)
    gates = {'last_run': last_run.isoformat() if last_run else None,
             'hours_since': round((moment - last_run).total_seconds() / 3600, 2) if last_run else None,
             'new_receipts': stats['count'], 'min_hours': min_hours, 'min_receipts': min_receipts,
             'locked': _locked(state), 'blocked_by': []}
    blocked = gates['blocked_by']
    if gates['locked']:
        blocked.append('lock')
    if last_run is not None and gates['hours_since'] < min_hours:
        blocked.append('min_hours')
    if last_run is not None and gates['new_receipts'] < min_receipts:
        blocked.append('min_receipts')
    gates['passed'] = not blocked
    return gates


def _note_files(vault):
    root = Path(vault)
    files = []
    for tree in NOTE_TREES:
        base = root / tree
        if base.is_dir():
            files.extend(sorted(path for path in base.rglob('*.md') if path.is_file()))
    return files


def inventory(vault, limits=None, extra=()):
    # limits: {vault-relative path: character cap} from the companion hygiene budgets.
    # extra: further vault-relative paths measured against the shared note cap
    # (the companion handoff files, whose directory is a local convention).
    caps = dict(limits or {})
    files = _note_files(vault)
    oversize = []

    def entry_for(relative, chars):
        cap = caps.get(relative)
        if chars > NOTE_CAP_CHARS or (cap is not None and chars > cap):
            limit = cap if cap is not None and cap > NOTE_CAP_CHARS else NOTE_CAP_CHARS
            return {'path': relative, 'chars': chars, 'cap': limit, 'generated': is_generated(relative)}
        return None

    for path in files:
        relative = path.relative_to(Path(vault)).as_posix()
        found = entry_for(relative, len(path.read_text(encoding='utf-8')))
        if found:
            oversize.append(found)
    for relative in tuple(SIZE_CHECKED) + tuple(extra):
        path = Path(vault) / relative
        if not path.is_file() or any(entry['path'] == relative for entry in oversize):
            continue
        found = entry_for(relative, len(path.read_text(encoding='utf-8')))
        if found:
            oversize.append(found)
    for pattern in GENERATED_GLOBS:
        for path in sorted(Path(vault).glob(pattern)):
            if not path.is_file():
                continue
            relative = path.relative_to(Path(vault)).as_posix()
            found = entry_for(relative, len(path.read_text(encoding='utf-8')))
            if found:
                oversize.append(found)
    oversize.sort(key=lambda entry: entry['path'])
    return {'notes': len(files), 'chars': sum(len(path.read_text(encoding='utf-8')) for path in files),
            'oversize': oversize}


def _tokens(title):
    folded = unicodedata.normalize('NFKD', str(title or ''))
    ascii_only = ''.join(char for char in folded if not unicodedata.combining(char))
    return {token for token in re.split(r'[^0-9a-z]+', ascii_only.lower()) if token}


def _age_days(record, vault, now):
    stamp = _parse(record.get('updated_at'))
    if stamp is None:
        source = Path(vault) / str(record.get('source') or '')
        if not source.is_file():
            return None
        stamp = dt.datetime.fromtimestamp(source.stat().st_mtime, dt.timezone.utc)
    return (now - stamp).days


def _title(record):
    # A synced record carries no derived title: the heading lives in the body. Fall back
    # through frontmatter title, first heading, then the source stem.
    title = record.get('title')
    if isinstance(title, str) and title.strip():
        return title
    for line in str(record.get('text') or '').splitlines():
        stripped = line.strip()
        if stripped.startswith('#'):
            heading = stripped.lstrip('#').strip()
            if heading:
                return heading
    source = str(record.get('source') or '')
    return source.rsplit('/', 1)[-1][:-3] if source.endswith('.md') else source


def _merge_pairs(records, citations):
    # Only cited notes, and only headings that share at least two words with one contained in
    # the other. The window proposes; a human or the session agent decides.
    eligible = [record for record in records
                if citations.get(str(record.get('source') or ''), 0) > 0 and _tokens(_title(record))]
    pairs, used = [], set()
    for first_index, first in enumerate(eligible):
        if first['source'] in used:
            continue
        first_tokens = _tokens(_title(first))
        for second in eligible[first_index + 1:]:
            if second['source'] in used:
                continue
            second_tokens = _tokens(_title(second))
            if len(first_tokens) < 2 or len(second_tokens) < 2:
                continue
            if first_tokens <= second_tokens or second_tokens <= first_tokens:
                used.update((first['source'], second['source']))
                pairs.append({'sources': sorted((first['source'], second['source'])),
                              'shared': sorted(first_tokens & second_tokens)})
                break
    return sorted(pairs, key=lambda pair: pair['sources'])


def candidates(vault, store, citations, oversize, now=None, stale_days=STALE_DAYS):
    moment = _now(now)
    records = store.list_records()
    prune, cited_pairs = [], _merge_pairs(records, citations)
    for record in records:
        source = str(record.get('source') or '')
        age = _age_days(record, vault, moment)
        if (record.get('status') == PRUNE_MARKER and age is not None and age >= stale_days
                and citations.get(source, 0) == 0):
            prune.append({'source': source, 'age_days': age})
    prune.sort(key=lambda entry: entry['source'])
    # Refresh rewrites a human source. Generated indexes are reported by size and repaired
    # by whatever produces them, never by a window.
    refresh = [{'path': entry['path'], 'chars': entry['chars']} for entry in oversize
               if not entry['generated']]
    return {'prune': prune, 'merge': cited_pairs, 'refresh': refresh}


def report(vault, state, store, now=None, limits=None, extra=()):
    gates = gate_status(vault, state, store, now=now)
    stats = store.receipt_stats()
    found = inventory(vault, limits=limits, extra=extra)
    return {'phase': 1, 'wrote': False, 'model_calls': False, 'network': False,
            'gates': gates, 'inventory': found, 'heat': stats['citations'],
            'candidates': candidates(vault, store, stats['citations'], found['oversize'], now=now)}


def render(result):
    return json.dumps(result, ensure_ascii=False, sort_keys=True)
