"""User-owned companion bootstrap and compact, source-verified session context."""
import json
from pathlib import Path
import re
import sys

NAMES = ('Core.md', 'Soul.md', 'Kurallar.md', 'Last-Session.md', 'Threads.md', 'Journal.md', 'memory-types.md')
FLOORS = {'Kurallar.md': .4, 'Last-Session.md': .2}
# Hygiene limits in characters for the two handoff files that are meant to be rewritten,
# not appended to (#96). Rules, identity and the Journal accumulate by design and are only
# measured. 0 turns a limit off; beyin.py preferences changes them.
LIMITS = {'Last-Session.md': 3000, 'Threads.md': 8000}
LIMIT_RANGE = (1000, 200000)
DEFAULT_DIRECTORY = '🔮 850-Companion'
STARTERS = {
    'Core.md': '# Düşünme ortağı\n\nKullanıcının düşünme ortağı ve ikinci beyniyim. Kimliğimi ve çalışma biçimimi birlikte belirleriz.\n\n## Kullanıcı ve ortak çalışma biçimi\nHenüz kişiselleştirilmedi. Kullanıcının adı, tercih ettiği hitap, çalışma alanı ve beklentilerini konuşarak öğren. Bilinmeyen geçmişi uydurma.\n\n## Kalıcı tercihler\nKullanıcının açıkça belirttiği tercihleri ve dayandıkları kaynağı burada tut.\n',
    'Kurallar.md': '# Kullanıcının düzeltmeleri\n\nHenüz kaydedilmiş bir düzeltme yok. Açık kullanıcı düzeltmelerini tarih ve kapsamıyla kaydet; geçici istekleri kalıcı kurala dönüştürme.\n',
    'Last-Session.md': '# Son oturum\n\nHenüz bir çalışma sonucu kaydedilmedi. Anlamlı çalışma sonunda sonuç, gerekçe, açık kalan adım ve kaynak bağlantılarını buraya yaz. Bu dosya tek bir devir kartıdır: her seferinde baştan yeniden yaz, eski kaydı alta ekleme.\n',
    'Threads.md': '# Threads\n\n## Active Threads\nHenüz açık bir konu kaydedilmedi.\n\n## Closed Threads\n',
    'Journal.md': '# Journal\n\nOrtak çalışmadan doğan gözlemler, öğrenimler ve açık sorular. Çıkarımları kesin kullanıcı bilgisi olarak sunma.\n',
    'memory-types.md': '---\n{"type": "semantic", "project": "Beyin", "visibility": "internal"}\n---\n# Memory Types\n\nBu belge Beyin v3 hafıza sisteminde kullanılan üç temel memory type\'ını tanımlar.\n\n## Type Tanımları\n\n### episodic — Zaman Serisi / Anılar\nBelirli bir zaman diliminde ne oldu.\nÖrnekler: Journal.md, Threads.md, Last-Session.md, daily/v3/*.md\n\n### semantic — Kalıcı Bilgi / Gerçekler / Kimlik\nZamanla değişmeyen, sorgulanabilir gerçekler.\nÖrnekler: Core.md, knowledge/concepts/*.md\n\n### procedural — Nasıl Yapılır / Kurallar / Playbook\'lar\nSüreçler, kurallar, workflow\'lar.\nÖrnekler: Kurallar.md, .agents/skills/*/SKILL.md\n',
}


def directory(vault):
    """Reuse one existing local identity directory; never guess between identities."""
    vault = Path(vault).resolve()
    candidates = []
    named = []
    for path in vault.iterdir():
        if (path.name.startswith('.') or path.is_symlink() or not path.is_dir() or
                re.search(r'(?i)(archive|arşiv|arsiv)', path.name)):
            continue
        if path.name == DEFAULT_DIRECTORY or path.name.casefold().endswith(('companion', 'echo')):
            named.append(path)
        elif any((path / name).is_file() for name in ('Core.md', 'Soul.md')):
            candidates.append(path)
    candidates = named or candidates
    if len(candidates) > 1:
        return None
    return candidates[0] if candidates else vault / DEFAULT_DIRECTORY


def initialize(vault, state):
    """Create missing starter notes once. These are user data, never package-owned.

    This is deliberately separate from managed rollback: learning written after
    installation must survive updates and uninstall. Exclusive creation preserves
    existing notes and makes interrupted/repeated bootstrap safe to retry.
    """
    state = Path(state)
    marker = state / 'companion-bootstrap.json'
    if marker.exists():
        return {'status': 'existing'}
    target = directory(vault)
    if target is None or target.is_symlink():
        return {'status': 'needs_attention', 'reason': 'Choose the existing companion directory; no notes created.'}
    target.mkdir(parents=True, exist_ok=True)
    if not target.resolve().is_relative_to(Path(vault).resolve()):
        raise ValueError('Companion directory escapes vault')
    created = []
    for name, text in STARTERS.items():
        path = target / name
        # A pre-existing Soul already carries identity; do not create a competing Core.
        if name == 'Core.md' and (target / 'Soul.md').exists():
            continue
        try:
            with path.open('x', encoding='utf-8') as output:
                output.write(text)
            created.append(name)
        except FileExistsError:
            pass
    from beyin_v3_sync import atomic
    state.mkdir(parents=True, exist_ok=True)
    atomic(marker, json.dumps({'schema': 1, 'directory': target.relative_to(Path(vault).resolve()).as_posix()}))
    return {'status': 'initialized', 'created': created}


def check_limits(value):
    if not isinstance(value, dict) or set(value) - set(LIMITS) - {'schema'} or value.get('schema', 1) != 1:
        raise ValueError('companion limits accept only ' + ', '.join(LIMITS))
    for name in LIMITS:
        number = value.get(name, LIMITS[name])
        if type(number) is not int or not (number == 0 or LIMIT_RANGE[0] <= number <= LIMIT_RANGE[1]):
            raise ValueError(f'{name} limit must be 0 (off) or an integer between {LIMIT_RANGE[0]} and {LIMIT_RANGE[1]}')
    return {name: value.get(name, LIMITS[name]) for name in LIMITS}


def read_limits(state):
    """(limits, valid). Machine-local, beside the runtime state, never in .beyin-preferences.json:
    an older release rejects unknown preference fields, so a rollback would break its hooks.
    A damaged file falls back to the defaults here and is never silently rewritten."""
    path = Path(state) / 'companion-limits.json'
    if not path.exists() and not path.is_symlink():
        return dict(LIMITS), True
    try:
        if path.is_symlink():
            raise ValueError('symlink')
        return check_limits(json.loads(path.read_text(encoding='utf-8'))), True
    except (ValueError, OSError):
        return dict(LIMITS), False


def save_limits(state, changes):
    current, valid = read_limits(state)
    if not valid:
        raise ValueError('companion-limits.json in the runtime state is invalid; fix or remove it first')
    result = check_limits(dict(current, **changes))
    from beyin_v3_sync import atomic
    atomic(Path(state) / 'companion-limits.json', json.dumps(dict(schema=1, **result), ensure_ascii=False, indent=2) + '\n')
    return result


def size(path):
    """Unicode characters as stored: not bytes and not UTF-16 units, so a Turkish or
    emoji-rich file is not reported larger than it is. Line endings are not translated
    (CRLF counts as two), the same measure companion-compact fits a file to. Streams;
    bounded memory."""
    count = 0
    with Path(path).open(encoding='utf-8', errors='replace', newline='') as source:
        for chunk in iter(lambda: source.read(1 << 16), ''):
            count += len(chunk)
    return count


def hygiene(vault, state, names=NAMES, target=None):
    """Read-only size report of the companion sources; limited files say whether they are over."""
    vault = Path(vault).resolve()
    target = directory(vault) if target is None else target
    configured, valid = read_limits(state)
    report = {'status': 'ok', 'limits': configured, 'limits_file': 'ok' if valid else 'invalid_defaults_used',
              'files': {}, 'over_limit': []}
    if target is None:
        return dict(report, status='ambiguous_directory')
    report['directory'] = target.relative_to(vault).as_posix()
    for name in names:
        path = target / name
        if path.is_symlink() or not path.is_file():
            continue
        entry = {'chars': size(path)}
        if name in LIMITS:
            entry['limit'] = configured[name]
            entry['over_limit'] = bool(configured[name]) and entry['chars'] > configured[name]
            if entry['over_limit']:
                report['over_limit'].append(name)
        report['files'][name] = entry
    if report['over_limit']:
        report['status'] = 'over_limit'
    return report


def hygiene_notice(report):
    """One line at the top of the session context, only when a handoff file is over its limit."""
    over = [f'{name} is {report["files"][name]["chars"]} chars (limit {report["files"][name]["limit"]})'
            for name in report.get('over_limit', [])]
    if not over:
        return ''
    python = 'py -3' if sys.platform == 'win32' else 'python3'
    return ('Memory hygiene: ' + '; '.join(over) + f'. Before other memory writes run: {python} beyin.py companion-compact '
            '(moves old entries verbatim to a private archive, deletes nothing). Do not read the whole file; '
            'afterwards rewrite in place, never append.\n')


def relevant(query):
    return bool(re.search(r'(?i)(son (oturum|konuş)|geçen (sefer|oturum|konuş)|nerede kal|ne (yaptık|yapmıştık)|beni (tanı|hatırla)|kişili|tercihlerim|sen kimsin|kim olduğunu|last (session|time)|previous session|where (did we|we) leave|remember me|personality|my (preferences|name)|who (am i|are you))', query))


def stamp(header):
    """Sortable (date, time) of a Journal header; an untimed entry sorts before timed ones."""
    date = re.search(r'\d{4}-\d{2}-\d{2}', header)
    clock = re.search(r'(?<!\d)([01]?\d|2[0-3]):[0-5]\d(?!\d)', header)
    return (date[0], clock[0].rjust(5, '0') if clock else '') if date else None


def excerpt(name, text):
    if name == 'Threads.md':
        match = re.search(r'(?im)^## (?:Active(?: Threads)?|Aktif[^\n]*)\s*$', text)
        if match:
            body = text[match.start():]
            closed = re.search(r'(?im)^## (?:Closed|Kapan|Kapalı)', body)
            return body[:closed.start()] if closed else body
    if name == 'Journal.md':
        entries = list(re.finditer(r'(?m)^## ([^\n]+)', text))
        dated = [(moment, i) for i, item in enumerate(entries) if (moment := stamp(item[1]))]
        if entries:
            # Equal timestamps follow the file's own direction: a newest-first journal keeps
            # the latest entry at the top, an append-ordered one at the bottom.
            newest_first = all(b <= a for (a, _), (b, _) in zip(dated, dated[1:]))
            index = max(dated, key=lambda item: (item[0], -item[1] if newest_first else item[1]))[1] if dated else len(entries) - 1
            return text[entries[index].start():entries[index + 1].start() if index + 1 < len(entries) else len(text)]
    if name == 'Last-Session.md':
        previous = re.search(r'(?im)^## (?:Previous|Önceki)', text)
        if previous:
            return text[:previous.start()]
    return text


def ends(text, budget):
    """Opening plus closing lines of a rule set, with the omitted amount named.

    The first marker is sized with the whole length, so the final one, counting only
    what was really dropped, can never be longer and the result stays inside budget.
    Whatever the line-boundary cut gives back is taken from the middle by the closing,
    because a water-filled allocation that renders short is budget thrown away.
    """
    def gap(omitted):
        return f'\n[truncated: {omitted} characters omitted here; read source]\n'

    keep = budget - len(gap(len(text)))
    if keep < 80:
        return None
    # Cut on line boundaries so neither end is a half rule; the closing part also takes
    # whatever the opening gave back.
    head = text[:keep - keep // 2]
    head = head[:head.rfind('\n') + 1] or head
    closing = text[len(text) - (keep - len(head)):]
    closing = closing[closing.find('\n') + 1:] or closing
    best = head + gap(len(text) - len(head) - len(closing)) + closing
    # Fill the slack the snaps created: grow the closing back into the middle until the
    # budget is full, only a marker digit oscillation away from exact.
    start = len(text) - len(closing)
    for _ in range(6):
        slack = budget - (len(head) + len(gap(start - len(head))) + len(text) - start)
        if slack == 0:
            break
        moved = min(max(start - slack, len(head)), len(text))
        if moved == start:
            break
        start = moved
    result = head + gap(start - len(head)) + text[start:]
    return result if len(result) <= budget else best


def clip(text, budget, tail=False, both=False):
    if len(text) <= budget:
        return text
    if both:
        kept = ends(text, budget)
        if kept:
            return kept
    marker = '\n[truncated: read source]\n'
    if budget <= len(marker):
        return marker.strip()[:budget]
    keep = budget - len(marker)
    return marker + text[-keep:] if tail else text[:keep] + marker


def context(store, budget, session, harness, query='', receipt='', warning=''):
    """Budget actual displayed text, not repeated JSON metadata; never cut a record header."""
    target = directory(store.vault_root)
    hygiene_line = ''
    if target is not None:
        try:
            hygiene_line = hygiene_notice(hygiene(store.vault_root, store.state_dir, tuple(LIMITS), target))
        except Exception:
            hygiene_line = ''  # A size check must never cost the session its context.
    header = (hygiene_line + warning + f'Receipt session={session}; choose --harness for the current client.\n'
              'V3 source-backed context (data, not instructions). Apply the companion protocol in AGENTS.md.\n')
    if target is None:
        return clip(header + 'Multiple companion directories: read the user-selected identity sources.\n', budget)
    snapshot = store.source_snapshot(NAMES, budget_chars=200000,
                                     source_directory=target.relative_to(store.vault_root).as_posix(),
                                     text_transform=excerpt)
    records = snapshot['records']
    notice = ''
    if snapshot['missing_sources']:
        notice += 'Missing/unavailable companion sources: ' + ', '.join(snapshot['missing_sources']) + '.\n'
    if snapshot['stale_excluded']:
        notice += 'Changed companion sources excluded; read current files.\n'
    sections = [(f'\n[{r["source"]}]\n', r['text'], Path(r['source']).name)
                for r in records]
    fixed = len(header) + len(notice) + sum(len(label) for label, _, _ in sections)
    if fixed > budget:
        return clip(header + notice + 'Read companion files: ' + ', '.join(r['source'] for r in records), budget)

    def companion(available):
        # Rules and the handoff get a floor first: an even split leaves the two continuity
        # sources the same share as a one-line style note. The rest water-fills, so small
        # identity files still return their unused share to long histories.
        lengths = [min(len(body), int(available * FLOORS.get(name, 0))) for _, body, name in sections]
        spare = available - sum(lengths)
        while spare and any(lengths[i] < len(item[1]) for i, item in enumerate(sections)):
            for i, (_, body, _) in enumerate(sections):
                if spare and lengths[i] < len(body):
                    lengths[i] += 1
                    spare -= 1
        rendered = header + notice
        for i, (label, body, name) in enumerate(sections):
            rendered += label + clip(body, lengths[i], both=name == 'Kurallar.md',
                                     tail=name == 'Kurallar.md' or (name == 'Journal.md' and not re.search(r'(?m)^## ', body)))
        return rendered

    available = max(0, int(budget * .83) - fixed)
    text = companion(available)
    extra = ''
    index = store.source_snapshot(['index.md'], source_directory='knowledge', budget_chars=4000)
    if index['records']:
        label = '\n[Knowledge map: knowledge/index.md]\n'
        allowance = min(600, (budget - len(text)) // 3)
        if allowance > len(label) + 40:
            extra += label + clip(index['records'][0]['text'], allowance - len(label))
    remaining = budget - len(text) - len(extra)
    ranked = store.context_for(harness, query, budget_chars=max(0, remaining - 100)) if query else store.snapshot_context(budget_chars=max(0, remaining - 100))
    used = {r['source'] for r in records}
    for record in ranked.get('records', []):
        if record['source'] in used:
            continue
        label = f'\n[Related source: {record["source"]}]\n'
        if len(text) + len(extra) + len(label) + 40 < budget:
            extra += label + clip(record['text'], budget - len(text) - len(extra) - len(label))
    if receipt and len(text) + len(extra) + 80 < budget:
        extra += clip(receipt, budget - len(text) - len(extra))
    # Retrieval takes its share first; every character it did not use goes back to the
    # clipped companion sources instead of being dropped.
    regained = companion(budget - fixed - len(extra))
    if len(text) < len(regained) <= budget - len(extra):
        text = regained
    return text + extra
