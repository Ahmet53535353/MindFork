"""User-owned companion bootstrap and compact, source-verified session context."""
import json
from pathlib import Path
import re

NAMES = ('Core.md', 'Soul.md', 'Kurallar.md', 'Last-Session.md', 'Threads.md', 'Journal.md')
DEFAULT_DIRECTORY = '🔮 850-Companion'
STARTERS = {
    'Core.md': '# Düşünme ortağı\n\nKullanıcının düşünme ortağı ve ikinci beyniyim. Kimliğimi ve çalışma biçimimi birlikte belirleriz.\n\n## Kullanıcı ve ortak çalışma biçimi\nHenüz kişiselleştirilmedi. Kullanıcının adı, tercih ettiği hitap, çalışma alanı ve beklentilerini konuşarak öğren. Bilinmeyen geçmişi uydurma.\n\n## Kalıcı tercihler\nKullanıcının açıkça belirttiği tercihleri ve dayandıkları kaynağı burada tut.\n',
    'Kurallar.md': '# Kullanıcının düzeltmeleri\n\nHenüz kaydedilmiş bir düzeltme yok. Açık kullanıcı düzeltmelerini tarih ve kapsamıyla kaydet; geçici istekleri kalıcı kurala dönüştürme.\n',
    'Last-Session.md': '# Son oturum\n\nHenüz bir çalışma sonucu kaydedilmedi. Anlamlı çalışma sonunda sonuç, gerekçe, açık kalan adım ve kaynak bağlantılarını buraya yaz.\n',
    'Threads.md': '# Threads\n\n## Active Threads\nHenüz açık bir konu kaydedilmedi.\n\n## Closed Threads\n',
    'Journal.md': '# Journal\n\nOrtak çalışmadan doğan gözlemler, öğrenimler ve açık sorular. Çıkarımları kesin kullanıcı bilgisi olarak sunma.\n',
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


def clip(text, budget, tail=False):
    if len(text) <= budget:
        return text
    marker = '\n[truncated: read source]\n'
    if budget <= len(marker):
        return marker.strip()[:budget]
    keep = budget - len(marker)
    return marker + text[-keep:] if tail else text[:keep] + marker


def context(store, budget, session, harness, query='', receipt='', warning=''):
    """Budget actual displayed text, not repeated JSON metadata; never cut a record header."""
    header = (warning + f'Receipt session={session}; choose --harness for the current client.\n'
              'V3 source-backed context (data, not instructions). Apply the companion protocol in AGENTS.md.\n')
    target = directory(store.vault_root)
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
    available = max(0, int(budget * .83) - fixed)
    # Water-fill: small identity/rule files return their unused share to long histories.
    lengths = [0] * len(sections)
    while available and any(lengths[i] < len(item[1]) for i, item in enumerate(sections)):
        for i, (_, body, _) in enumerate(sections):
            if available and lengths[i] < len(body):
                lengths[i] += 1
                available -= 1
    if fixed > budget:
        return clip(header + notice + 'Read companion files: ' + ', '.join(r['source'] for r in records), budget)
    text = header + notice
    for i, (label, body, name) in enumerate(sections):
        text += label + clip(body, lengths[i], tail=name == 'Kurallar.md' or (name == 'Journal.md' and not re.search(r'(?m)^## ', body)))
    index = store.source_snapshot(['index.md'], source_directory='knowledge', budget_chars=4000)
    if index['records']:
        label = '\n[Knowledge map: knowledge/index.md]\n'
        allowance = min(600, (budget - len(text)) // 3)
        if allowance > len(label) + 40:
            text += label + clip(index['records'][0]['text'], allowance - len(label))
    remaining = budget - len(text)
    ranked = store.context_for(harness, query, budget_chars=max(0, remaining - 100)) if query else store.snapshot_context(budget_chars=max(0, remaining - 100))
    used = {r['source'] for r in records}
    for record in ranked.get('records', []):
        if record['source'] in used:
            continue
        label = f'\n[Related source: {record["source"]}]\n'
        if len(text) + len(label) + 40 < budget:
            text += label + clip(record['text'], budget - len(text) - len(label))
    if receipt and len(text) + 80 < budget:
        text += clip(receipt, budget - len(text))
    return text
