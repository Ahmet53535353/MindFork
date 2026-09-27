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

import contextlib
import datetime as dt
from fnmatch import fnmatch
import hashlib
import json
import os
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


# ---------------------------------------------------------------------------
# Faz 2: snapshot, Refresh, geri al
# Spec: docs/specs/2026-09-26-autodream-phase2-snapshot-refresh-plan.md
# ---------------------------------------------------------------------------

ARCHIVE_ROOT = 'archive/auto-dream'
MANIFEST = 'manifest.json'
WATERMARK = 'dream.last_run'
# A session count in state, not the 24 hour rule: a diagnosis run must be able to
# open the window on demand without a day of waiting.
FORCE_HOURS = 0.0

_DOTLESS_I = str.maketrans({'ı': 'i', 'İ': 'i', 'I': 'i'})

# Bağıl tarih ifadeleri. Kelime sınırı zorunlu: "dünya", "dünleyici" bunları
# içerir ama tarih değildir. "öğleden sonra" gibi zaman ifadeleri bilinçli
# dışarıda: tarih mutlaklaştırmanın işi, saat anlatısı değil.
RELATIVE_DATES = ('dün', 'bugün', 'geçen gün', 'dün akşam', 'dün sabah', 'bu sabah',
                  'geçen hafta', 'geçen ay', 'geçen yıl', 'bir süre önce', 'birkaç gün önce',
                  'birkaç hafta önce', 'önceki gün')

_FRONTMATTER = re.compile(r'\A(---\r?\n)(.*?)(\r?\n---\r?\n?)', re.S)
_JSON_LINE = re.compile(r'\A\s*(\{.*\})\s*\Z', re.S)
_FIELD = re.compile(r'\A\s*([A-Za-z_][A-Za-z0-9_-]*)\s*:\s*(.*?)\s*\Z')


def _fold(text):
    """Turkish-aware folding so the phrase list can stay ASCII (see companion._fold)."""
    decomposed = unicodedata.normalize('NFKD', text.lower().translate(_DOTLESS_I))
    return ''.join(character for character in decomposed if not unicodedata.combining(character))


def _phrase_pattern(phrases):
    # \b does not fire after a dotless fold in every engine, so the guard is explicit:
    # the character before and after the phrase must not be a letter.
    return re.compile(r'(?<![0-9a-z])(' + '|'.join(sorted(map(_fold, phrases), key=len, reverse=True)) + r')(?![0-9a-z])')


_RELATIVE_RE = _phrase_pattern(RELATIVE_DATES)
_TRAILING = re.compile(r'[ \t]+$', re.M)
_BLANK_RUN = re.compile(r'\n{3,}')
_LINE_END = '\n'


def _date_or_none(value):
    """An ISO date or the date part of an ISO timestamp, or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return dt.date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _window_dir(vault, day):
    return Path(vault) / ARCHIVE_ROOT / day


def _read_frontmatter(text):
    """((open, raw, close), body, meta) for the one-line JSON form and for plain YAML keys.

    The fence pieces keep their original bytes, so a normalization that changes nothing
    puts them back untouched, and one that does change a field rewrites only that field.
    """
    match = _FRONTMATTER.match(text)
    if match is None:
        return None, text, {}
    parts = (match.group(1), match.group(2), match.group(3))
    raw, body = match.group(2), text[match.end():]
    meta = {}
    line = _JSON_LINE.match(raw)
    if line is not None:
        try:
            parsed = json.loads(line.group(1))
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            for key, value in parsed.items():
                if isinstance(value, str):
                    meta[key] = value
            return parts, body, meta
    for entry in raw.splitlines():
        field = _FIELD.match(entry)
        if field is not None:
            meta[field.group(1)] = field.group(2).strip('"\'')
    return parts, body, meta


def _replace_field(raw, key, value):
    """Rewrite one field's value in place, leaving key order and layout alone.

    Re-serializing the whole frontmatter would reorder the user's keys for no reason;
    a window that tidies whitespace has no business reformatting metadata.
    """
    quoted = re.compile(r'("' + re.escape(key) + r'"\s*:\s*)"[^"]*"')
    if quoted.search(raw):
        return quoted.sub(lambda match: match.group(1) + json.dumps(value, ensure_ascii=False),
                          raw, count=1)
    plain = re.compile(r'(?m)^(' + re.escape(key) + r'\s*:\s*)(.*)$')
    return plain.sub(lambda match: match.group(1) + value, raw, count=1)


def prose_dates(text):
    """Relative date phrases in the body, as {line, phrase}. Reported, never rewritten.

    The agent owns prose: §5.1 of the roadmap splits Refresh in two, and this is the
    reporting half. Word-boundary matching keeps "dünya" and "dünleyici" out, and the
    reported phrase is the user's own spelling: `_fold` maps every character to exactly
    one character, so a span in the folded line is the same span in the original.
    """
    found = []
    for number, line in enumerate(text.splitlines(), 1):
        for match in _RELATIVE_RE.finditer(_fold(line)):
            found.append({'line': number, 'phrase': line[match.start():match.end()]})
    return found


def normalize(text, as_of=None):
    """Deterministic, idempotent clean-up: whitespace, and machine-owned date fields.

    Only what this function owns is written back. Prose relative dates are reported
    and left in place; human sentences are the agent's (§4, §5.1). A frontmatter date
    is resolved against the note's own recorded date, never guessed from today's
    clock, so the same note normalizes the same way forever.
    """
    parts, body, meta = _read_frontmatter(text)
    changes = []
    anchor = _date_or_none(meta.get('updated')) or _date_or_none(meta.get('created'))
    if parts is not None and anchor is not None:
        open_fence, raw, close_fence = parts
        for key, value in meta.items():
            if _RELATIVE_RE.search(_fold(value)):
                raw = _replace_field(raw, key, anchor.isoformat())
                changes.append(f'{key}: bağıl tarih mutlaklaştırıldı')
        parts = (open_fence, raw, close_fence)
    cleaned_body = _BLANK_RUN.sub('\n\n', _TRAILING.sub('', body).rstrip('\n') + _LINE_END)
    if cleaned_body != body:
        changes.append('başlık/ayraç normalleştirildi')
    head = ''.join(parts) if parts is not None else ''
    return head + cleaned_body, changes, meta


def snapshot(vault, sources, now=None):
    """Copy every file a window will touch, then write the manifest that restore trusts.

    The archive sits outside the note trees on purpose: a pre-image must never show
    up in the next window's own candidate list.
    """
    day = _now(now).date().isoformat()
    target = _window_dir(vault, day)
    entries = []
    for relative in sorted(set(sources)):
        path = Path(vault) / relative
        if not path.is_file():
            continue
        data = path.read_bytes()
        archived = f'{ARCHIVE_ROOT}/{day}/files/{relative}'
        copy = Path(vault) / archived
        copy.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(copy, data)
        entries.append({'source': relative, 'archive': archived,
                        'sha256': _sha256(data), 'chars': len(data.decode('utf-8', 'replace'))})
    manifest = {'schema': 1, 'window': day, 'created_at': _now(now).isoformat(), 'files': entries}
    _atomic_write(target / MANIFEST, (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    return manifest


def _atomic_write(path, data):
    """Same discipline as the rest of the engine: write beside, then replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(data)
    os.replace(temporary, path)


def restore(vault, day):
    """Put every pre-image back. A hash that no longer matches is refused, not guessed.

    Restore is the whole reason phase 2 is allowed to write, so a damaged archive is
    reported as an error instead of being loaded over a good note.
    """
    if not isinstance(day, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day or ''):
        raise ValueError('restore needs a YYYY-MM-DD window')
    target = _window_dir(vault, day)
    manifest_path = target / MANIFEST
    if not manifest_path.is_file():
        raise ValueError(f'no consolidation snapshot for {day}')
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    except ValueError as exc:
        raise ValueError(f'snapshot manifest is not readable: {exc}')
    if manifest.get('schema') != 1 or not isinstance(manifest.get('files'), list):
        raise ValueError('unsupported snapshot manifest')
    restored = []
    for entry in manifest['files']:
        archived = Path(vault) / str(entry.get('archive', ''))
        if not archived.is_file():
            raise ValueError(f'snapshot file missing: {entry.get("archive")}')
        data = archived.read_bytes()
        if _sha256(data) != entry.get('sha256'):
            raise ValueError(f'snapshot hash mismatch: {entry.get("source")}')
        source = Path(vault) / str(entry.get('source', ''))
        _atomic_write(source, data)
        restored.append(entry['source'])
    return {'restored': sorted(restored), 'window': day}


def apply_refresh(vault, candidates, now=None):
    """Write only what normalize() changed, and only for human sources.

    `updated` is deliberately not advanced here: a note whose body did not change
    must keep its recency, or every window would float old notes to the top of
    retrieval without changing a word of them.
    """
    moment = _now(now)
    applied, prose, skipped = [], [], []
    for entry in candidates:
        relative = entry.get('path')
        path = Path(vault) / relative
        if entry.get('generated') or not path.is_file():
            skipped.append(relative)
            continue
        text = path.read_text(encoding='utf-8')
        cleaned, changes, _meta = normalize(text, as_of=moment)
        found = prose_dates(text)
        if found:
            prose.append({'path': relative, 'dates': found})
        if cleaned == text:
            skipped.append(relative)
            continue
        _atomic_write(path, cleaned.encode('utf-8'))
        applied.append({'path': relative, 'changes': changes})
    return applied, prose, skipped


@contextlib.contextmanager
def _acquire(state):
    """Create the lock and hold it for a mutating window; report instead of waiting.

    Phase 1's read-only check never creates this file. A window that writes must
    take the lock for its whole run, so two consolidation windows cannot interleave.
    """
    path = Path(state) / 'dream.lock'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    handle = open(path, 'a+b')
    try:
        with _portalock.exclusive(handle, blocking=False) as acquired:
            yield acquired
    finally:
        handle.close()


def _gate_blockers(gates, force=False):
    """Translate a gate report into the reasons a mutating window must refuse.

    --force is a diagnosis switch: it clears the time and receipt waits but never
    the lock, because the lock protects this run's writes, not politeness.
    """
    blocked = list(gates['blocked_by'])
    if force:
        blocked = [reason for reason in blocked if reason == 'lock']
    return blocked


def window(vault, state, store, now=None, limits=None, extra=(), force=False):
    """A mutating consolidation window: gates enforced, pre-images first, then Refresh."""
    moment = _now(now)
    gates = gate_status(vault, state, store, now=moment)
    if force:
        gates = dict(gates, forced=True)
    with _acquire(state) as acquired:
        if not acquired:
            gates = dict(gates, locked=True, passed=False, blocked_by=['lock'])
        blocked = _gate_blockers(gates, force=force)
        if blocked:
            return {'phase': 2, 'wrote': False, 'model_calls': False, 'network': False,
                    'gates': dict(gates, passed=False, blocked_by=blocked),
                    'applied': [], 'prose_dates': [], 'skipped': [],
                    'snapshot': None, 'report_path': None, 'restore_command': None}
        stats = store.receipt_stats()
        found = inventory(vault, limits=limits, extra=extra)
        due = candidates(vault, store, stats['citations'], found['oversize'], now=moment)
        refreshable = [entry for entry in due['refresh'] if not entry.get('generated')]
        manifest = snapshot(vault, [entry['path'] for entry in refreshable], now=moment)
        applied, prose, skipped = apply_refresh(vault, refreshable, now=moment)
        wrote = bool(applied)
        day = manifest['window']
        report_path = None
        if wrote:
            # The watermark moves only when the window really changed something, or a
            # weekly measurement would close its own measurement window (the §0 trap).
            store.write_meta(WATERMARK, moment.isoformat())
            _write_report(vault, day, manifest, applied, prose, skipped)
            report_path = f'{ARCHIVE_ROOT}/{day}/report.md'
        return {'phase': 2, 'wrote': wrote, 'model_calls': False, 'network': False,
                'gates': dict(gates, passed=True, blocked_by=[]),
                'applied': applied, 'prose_dates': prose, 'skipped': skipped,
                'snapshot': manifest,
                'report_path': report_path,
                'restore_command': f'beyin.py dream --restore {day}' if wrote else None}


def _write_report(vault, day, manifest, applied, prose, skipped):
    lines = [f'# Konsolidasyon penceresi {day}', '',
             f"Geri al: `beyin.py dream --restore {day}`", '',
             f"- Ön-image: {len(manifest['files'])} dosya (`{ARCHIVE_ROOT}/{day}/files/`)",
             f"- Yeniden yazılan: {len(applied)}", f"- Değişmedi: {len(skipped)}", '']
    for entry in applied:
        lines.append(f"- **düzenlendi** `{entry['path']}`: {', '.join(entry['changes'])}")
    for entry in prose:
        for found in entry['dates']:
            lines.append(f"- **gövdede bağıl tarih** `{entry['path']}`:{found['line']} "
                         f"→ \"{found['phrase']}\" (metin ajana ait, değiştirilmedi)")
    _atomic_write(_window_dir(vault, day) / 'report.md',
                  ('\n'.join(lines) + '\n').encode('utf-8'))
