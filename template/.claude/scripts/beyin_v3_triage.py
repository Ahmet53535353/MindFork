"""Triage and digestion routines: inbox scanning, stale tasks, and weekly knowledge digest."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time

try:
    from beyin_v3_hygiene import (
        fold,
        sensitive_excluded,
        companion_names,
        INBOX_WORDS,
        TERMINAL_STATUSES,
        _inbox_folder,
        CODE_DIRS,
    )
except ImportError:
    _TR_FOLD = str.maketrans({'ş': 's', 'ğ': 'g', 'ü': 'u', 'ö': 'o', 'ç': 'c', 'ı': 'i', 'â': 'a', 'î': 'i', 'û': 'u'})

    def fold(text):
        import unicodedata
        t = unicodedata.normalize('NFC', str(text or '')).replace('İ', 'i').replace('I', 'i').lower()
        return unicodedata.normalize('NFC', t.replace('\u0307', '')).translate(_TR_FOLD)

    def sensitive_excluded(name):
        return False

    def companion_names(vault, state=None):
        return {'🔮 850-Companion', 'Companion', '850-Companion'}

    INBOX_WORDS = re.compile(r'(?:inbox|inboxes|gelenkutusu|gelenkutum)')
    TERMINAL_STATUSES = {'done', 'cancelled', 'kapandi'}
    CODE_DIRS = {'node_modules', 'venv', '.venv', '__pycache__'}

    def _inbox_folder(name, configured=None):
        f = fold(name)
        return 'inbox' in f or 'gelen' in f or 'kaynak' in f or 'source' in f or 'yakala' in f

EXTENDED_TERMINAL_STATUSES = frozenset(TERMINAL_STATUSES | {'completed', 'tamamlandi', 'iptal', 'closed'})

DATE_PATTERN = re.compile(r'(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?')


def _is_safe_file(path: Path) -> bool:
    name = path.name
    if name.startswith('.') or name.endswith('~') or name == '.gitkeep':
        return False
    return path.is_file() and not path.is_symlink()


def _front_values(text: str, keys: tuple[str, ...], fold_values: bool = True) -> dict[str, str]:
    """Frontmatter values for given keys from JSON or flat YAML."""
    if not text.startswith('---'):
        return {}
    lines = text.splitlines()
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == '---'), None)
    if end is None:
        return {}
    header = '\n'.join(lines[1:end]).strip()
    if header.startswith('{'):
        try:
            data = json.loads(header)
            if isinstance(data, dict):
                return {k: (fold(str(data[k])).strip() if fold_values else str(data[k]).strip())
                        for k in keys if k in data and data[k] is not None}
        except Exception:
            return {}
    found = {}
    for line in lines[1:end]:
        m = re.fullmatch(r'([^\W\d][\w-]*):[ \t]*(["\']?)([^"\'#]*?)\2[ \t]*(?:#.*)?', line.rstrip())
        if m and m[1] in keys and m[1] not in found:
            found[m[1]] = fold(m[3]).strip() if fold_values else m[3].strip()
    return found


def _parse_timestamp(val: str) -> float | None:
    if not val or not isinstance(val, str):
        return None
    match = DATE_PATTERN.search(val.strip())
    if not match:
        return None
    year, month, day = int(match[1]), int(match[2]), int(match[3])
    hour = int(match[4]) if match[4] else 0
    minute = int(match[5]) if match[5] else 0
    second = int(match[6]) if match[6] else 0
    try:
        dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
        return dt.timestamp()
    except (ValueError, OverflowError):
        return None


def _note_age_days(path: Path, now: float, front_keys: tuple[str, ...]) -> float:
    """Age of a note in days, prioritized by frontmatter date keys for sync immunity,

    falling back to file mtime if no valid frontmatter date is present.
    """
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return 0.0

    try:
        with path.open(encoding='utf-8', errors='replace') as handle:
            head = handle.read(4096)
        values = _front_values(head, front_keys, fold_values=False)
        for k in front_keys:
            raw = values.get(k)
            if raw:
                ts = _parse_timestamp(raw)
                if ts is not None:
                    return max(0.0, (now - ts) / 86400.0)
    except Exception:
        pass

    return max(0.0, (now - mtime) / 86400.0)


def _find_top_matching_dirs(vault: Path, matcher, extra_exact: tuple[str, ...] = ()) -> list[Path]:
    vault = Path(vault).resolve()
    matched = []
    seen = set()
    try:
        entries = sorted(vault.iterdir())
    except OSError:
        return []

    for entry in entries:
        if not entry.is_dir() or entry.is_symlink():
            continue
        name = entry.name
        if name.startswith('.') or sensitive_excluded(name) or name in CODE_DIRS:
            continue
        folded = fold(name)
        if matcher(name, folded) or folded in extra_exact:
            try:
                resolved = entry.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    matched.append(resolved)
            except OSError:
                pass
    return matched


def scan_inbox(vault: Path, now: float) -> dict:
    vault = Path(vault).resolve()
    items = []
    companions = companion_names(vault)
    seen_dirs = set()
    inbox_folders = []

    def is_inbox(name: str, folded: str) -> bool:
        if name in companions or sensitive_excluded(name):
            return False
        return (
            _inbox_folder(name, None)
            or folded in ('sources', 'kaynaklar', 'kaynak', 'yakala')
            or any(w in folded for w in ('inbox', 'gelenkutusu', 'gelenkutum'))
        )

    for folder in _find_top_matching_dirs(vault, is_inbox, extra_exact=('000-inbox', 'sources', 'kaynaklar')):
        try:
            res = folder.resolve()
            if res not in seen_dirs:
                seen_dirs.add(res)
                inbox_folders.append(res)
        except OSError:
            pass

    # If vault has a default starter folder not matched yet:
    for starter in ('📥 000-Inbox', '000-Inbox', 'sources', 'Sources', 'Kaynaklar'):
        folder = vault / starter
        if folder.is_dir() and not folder.is_symlink():
            try:
                res = folder.resolve()
                if res not in seen_dirs:
                    seen_dirs.add(res)
                    inbox_folders.append(res)
            except OSError:
                pass

    for folder in inbox_folders:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in CODE_DIRS]
            for f in files:
                file_path = Path(root) / f
                if not _is_safe_file(file_path):
                    continue

                # Skip already processed yakala cards
                if file_path.suffix.lower() == '.md':
                    try:
                        with file_path.open(encoding='utf-8', errors='replace') as handle:
                            head = handle.read(2048)
                        val = _front_values(head, ('tur', 'durum'), fold_values=True)
                        if val.get('tur') == 'yakala' and val.get('durum') == 'islendi':
                            continue
                    except OSError:
                        continue

                age = _note_age_days(file_path, now, ('created', 'created_at', 'yakalandi', 'date', 'tarih'))
                try:
                    rel = file_path.relative_to(vault).as_posix()
                except ValueError:
                    rel = str(file_path)

                ext = file_path.suffix.lower()
                kind = (
                    'note' if ext in ('.md', '.txt')
                    else 'data' if ext in ('.json', '.csv', '.yaml', '.yml')
                    else 'media' if ext in ('.png', '.jpg', '.jpeg', '.webp', '.mp4', '.m4a', '.mp3', '.pdf')
                    else 'file'
                )

                items.append({
                    'path': rel,
                    'name': f,
                    'kind': kind,
                    'age_days': round(age, 1),
                })

    items.sort(key=lambda x: x['age_days'], reverse=True)
    oldest = items[0] if items else None
    return {
        'count': len(items),
        'items': items,
        'oldest': oldest,
    }


def scan_stale_tasks(vault: Path, now: float, stale_days: int = 14) -> dict:
    vault = Path(vault).resolve()
    open_tasks = []
    stale_tasks = []
    seen_dirs = set()
    task_folders = []

    def is_task_dir(name: str, folded: str) -> bool:
        return 'task' in folded or 'gorev' in folded

    for folder in _find_top_matching_dirs(vault, is_task_dir, extra_exact=('tasks', '500-tasks', 'gorevler')):
        try:
            res = folder.resolve()
            if res not in seen_dirs:
                seen_dirs.add(res)
                task_folders.append(res)
        except OSError:
            pass

    for starter in ('tasks', 'Tasks', '500-Tasks', 'Görevler', 'Gorevler', '✅ 500-Tasks'):
        f = vault / starter
        if f.is_dir() and not f.is_symlink():
            try:
                res = f.resolve()
                if res not in seen_dirs:
                    seen_dirs.add(res)
                    task_folders.append(res)
            except OSError:
                pass

    for folder in task_folders:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in CODE_DIRS]
            for f in files:
                file_path = Path(root) / f
                if not _is_safe_file(file_path) or file_path.suffix.lower() != '.md':
                    continue

                try:
                    text = file_path.read_text(encoding='utf-8', errors='replace')
                except OSError:
                    continue

                status_val = _front_values(text[:4096], ('status', 'durum'), fold_values=True)
                status = status_val.get('status') or status_val.get('durum') or 'open'
                if not status:
                    status = 'open'

                # Check markdown content for status / checkboxes if not terminal from frontmatter
                if status not in EXTENDED_TERMINAL_STATUSES:
                    for line in text.splitlines():
                        m = re.match(r'(?i)^status:\s*([a-zA-Z_-]+)', line.strip())
                        if m:
                            st = m.group(1).lower()
                            if st in EXTENDED_TERMINAL_STATUSES:
                                status = st
                                break

                if status in EXTENDED_TERMINAL_STATUSES:
                    continue

                # Title
                raw_title_val = _front_values(text[:4096], ('title', 'baslik'), fold_values=False)
                title = raw_title_val.get('title') or raw_title_val.get('baslik') or ''
                if not title:
                    for line in text.splitlines():
                        sline = line.strip()
                        if sline.startswith('#'):
                            title = sline.lstrip('#').strip()
                            break
                if not title:
                    title = f.replace('.md', '')

                age = _note_age_days(file_path, now, ('updated_at', 'updated', 'modified', 'last_modified', 'date_modified', 'created_at', 'created', 'date'))
                try:
                    rel = file_path.relative_to(vault).as_posix()
                except ValueError:
                    rel = str(file_path)

                task_info = {
                    'path': rel,
                    'title': title,
                    'status': status,
                    'age_days': round(age, 1),
                }
                open_tasks.append(task_info)
                if age >= stale_days:
                    stale_tasks.append(task_info)

    stale_tasks.sort(key=lambda x: x['age_days'], reverse=True)
    return {
        'open_count': len(open_tasks),
        'stale_count': len(stale_tasks),
        'stale_days_threshold': stale_days,
        'stale_tasks': stale_tasks,
    }


def scan_knowledge_digest(vault: Path, now: float, digest_days: int = 7) -> dict:
    vault = Path(vault).resolve()
    recent_items = []
    seen_dirs = set()
    knowledge_folders = []

    def is_knowledge_dir(name: str, folded: str) -> bool:
        return 'knowledge' in folded or 'bilgi' in folded or 'decision' in folded or 'karar' in folded

    for folder in _find_top_matching_dirs(
        vault, is_knowledge_dir,
        extra_exact=('knowledge', '500-knowledge', 'decisions', 'bilgiler', 'kararlar')
    ):
        try:
            res = folder.resolve()
            if res not in seen_dirs:
                seen_dirs.add(res)
                knowledge_folders.append(res)
        except OSError:
            pass

    for starter in ('knowledge', 'Knowledge', '🧠 500-Knowledge', '500-Knowledge', 'decisions', 'Decisions'):
        f = vault / starter
        if f.is_dir() and not f.is_symlink():
            try:
                res = f.resolve()
                if res not in seen_dirs:
                    seen_dirs.add(res)
                    knowledge_folders.append(res)
            except OSError:
                pass

    for folder in knowledge_folders:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in CODE_DIRS]
            for f in files:
                file_path = Path(root) / f
                if not _is_safe_file(file_path) or file_path.suffix.lower() != '.md':
                    continue

                age = _note_age_days(
                    file_path, now,
                    ('updated_at', 'updated', 'modified', 'created_at', 'created', 'date', 'tarih')
                )
                if age <= digest_days:
                    try:
                        rel = file_path.relative_to(vault).as_posix()
                    except ValueError:
                        rel = str(file_path)

                    title = ''
                    try:
                        with file_path.open(encoding='utf-8', errors='replace') as handle:
                            head = handle.read(2048)
                        val = _front_values(head, ('title', 'baslik'), fold_values=False)
                        title = val.get('title') or val.get('baslik') or ''
                        if not title:
                            for line in head.splitlines():
                                sline = line.strip()
                                if sline.startswith('#'):
                                    title = sline.lstrip('#').strip()
                                    break
                    except OSError:
                        pass

                    if not title:
                        title = f.replace('.md', '')

                    recent_items.append({
                        'path': rel,
                        'title': title,
                        'age_days': round(age, 1),
                    })

    outcomes_file = vault / 'outcomes.md'
    if outcomes_file.is_file() and not outcomes_file.is_symlink():
        age = _note_age_days(outcomes_file, now, ('updated_at', 'date'))
        if age <= digest_days:
            recent_items.append({
                'path': 'outcomes.md',
                'title': 'Kazanimlar ve Sonuclar',
                'age_days': round(age, 1),
            })

    recent_items.sort(key=lambda x: x['age_days'])
    return {
        'digest_days': digest_days,
        'count': len(recent_items),
        'items': recent_items,
    }


def scan_companion(vault: Path, state: Path | None = None, now: float | None = None) -> dict:
    vault = Path(vault).resolve()
    info = {'rules_count': 0, 'active_threads': 0, 'last_session': None, 'active_presence': 0}
    comp_dir = None
    companions = companion_names(vault, state)

    for name in companions:
        c = vault / name
        if c.is_dir() and not c.is_symlink():
            comp_dir = c
            break

    if not comp_dir:
        for d in ('🔮 850-Companion', 'Companion', '850-Companion', 'companion'):
            c = vault / d
            if c.is_dir() and not c.is_symlink():
                comp_dir = c
                break

    if comp_dir:
        rules_file = comp_dir / 'Kurallar.md'
        if rules_file.is_file():
            try:
                text = rules_file.read_text(encoding='utf-8', errors='replace')
                info['rules_count'] = sum(1 for line in text.splitlines() if re.match(r'^(?:[-*+]|\d+[.)])[ \t]', line.strip()))
            except OSError:
                pass

        threads_file = comp_dir / 'Threads.md'
        if threads_file.is_file():
            try:
                text = threads_file.read_text(encoding='utf-8', errors='replace')
                lines = text.splitlines()
                in_active = False
                has_active_section = False
                active_lines = []
                for line in lines:
                    sline = line.strip()
                    if re.match(r'(?i)^##\s+(?:active|aktif|acik|açık)', sline):
                        in_active = True
                        has_active_section = True
                        continue
                    elif in_active and re.match(r'(?i)^##\s+(?:closed|kapan|onceki|önceki|arsiv|arşiv)', sline):
                        in_active = False
                        break
                    elif in_active:
                        active_lines.append(line)

                if not has_active_section:
                    for line in lines:
                        sline = line.strip()
                        if re.match(r'(?i)^##\s+(?:closed|kapan|onceki|önceki|arsiv|arşiv)', sline):
                            break
                        active_lines.append(line)

                active_text = '\n'.join(active_lines)
                headers = re.findall(r'(?m)^###\s+', active_text)
                if headers:
                    info['active_threads'] = len(headers)
                else:
                    info['active_threads'] = len(re.findall(
                        r'(?i)\*\*(?:status|durum):\*\*[ \t]*(?:[^\w\n]*)[ \t]*(?:active|aktif)',
                        active_text or text
                    ))
            except OSError:
                pass

        session_file = comp_dir / 'Last-Session.md'
        if session_file.is_file():
            try:
                text = session_file.read_text(encoding='utf-8', errors='replace')
                m = re.search(r'##\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})', text)
                if m:
                    info['last_session'] = m.group(1)
            except OSError:
                pass

    # Presence check for active sessions across devices
    presence_dir = vault / '.presence'
    if presence_dir.is_dir() and not presence_dir.is_symlink():
        active = 0
        now_ts = time.time() if now is None else now
        try:
            for p_file in presence_dir.glob('*.json'):
                try:
                    data = json.loads(p_file.read_text(encoding='utf-8'))
                    heartbeat = data.get('heartbeat') or p_file.stat().st_mtime
                    if now_ts - heartbeat < 2700:  # < 45 minutes
                        active += 1
                except Exception:
                    pass
        except OSError:
            pass
        info['active_presence'] = active

    return info


def generate_recommendations(inbox: dict, tasks: dict, digest: dict, companion: dict) -> list[str]:
    recs = []
    if inbox['count'] > 0:
        recs.append(
            f"Gelen kutusunda bekleyen {inbox['count']} kaynak var. Kalici bilgi notlarina donusturmek icin 'beyin-yakala' kullanin."
        )
    if tasks['stale_count'] > 0:
        recs.append(
            f"{tasks['stale_count']} gorev {tasks['stale_days_threshold']} gunden uzun suredir hareketsiz. Bu gorevleri tamamlayin, kapatin veya guncelleyin."
        )
    if companion.get('active_threads', 0) > 4:
        recs.append(
            f"Threads.md icinde {companion['active_threads']} aktif konu var. Tamamlananlari 'beyin.py companion-compact' ile arsivleyin."
        )
    if companion.get('rules_count', 0) > 35:
        recs.append(
            f"Kurallar.md dosyasinda {companion['rules_count']} kural birikmis. Ajanin dikkat penceresini rahatlatmak icin eski veya genel kurallari sadelestirin."
        )
    if digest['count'] == 0:
        recs.append(
            f"Son {digest['digest_days']} gunde yeni bilgi/karar notu uretilmedi. Ogrenilenleri knowledge/ altina damitin."
        )
    else:
        recs.append(
            f"Son {digest['digest_days']} gunde {digest['count']} bilgi notu uretildi/guncellendi; ritim saglikli."
        )
    return recs


def triage(
    vault: Path,
    state: Path | None = None,
    stale_days: int = 14,
    digest_days: int = 7,
    now: float | None = None,
) -> dict:
    now_ts = time.time() if now is None else now
    vault = Path(vault).resolve()
    inbox_report = scan_inbox(vault, now_ts)
    tasks_report = scan_stale_tasks(vault, now_ts, stale_days=stale_days)
    digest_report = scan_knowledge_digest(vault, now_ts, digest_days=digest_days)
    companion_report = scan_companion(vault, state, now=now_ts)
    recs = generate_recommendations(inbox_report, tasks_report, digest_report, companion_report)

    return {
        'schema': 1,
        'vault': str(vault),
        'generated_at': datetime.fromtimestamp(now_ts, timezone.utc).isoformat(),
        'inbox': inbox_report,
        'tasks': tasks_report,
        'digest': digest_report,
        'companion': companion_report,
        'recommendations': recs,
    }


def _strip_terminal_controls(text: str) -> str:
    return re.sub(r'[\x00-\x08\x0b-\x1f\x7f-\x9f]', '', text)


def format_human(report: dict) -> str:
    lines = ['=== Ikinci Beyin Sindirim ve Durum Raporu (Triage) ===\n']
    inbox = report.get('inbox', {})
    lines.append('[Gelen Kutusu / Yakalananlar]')
    lines.append(f"  Bekleyen kaynak: {inbox.get('count', 0)}")
    oldest = inbox.get('oldest')
    if oldest:
        lines.append(f"  En eski: {oldest.get('path')} ({oldest.get('age_days', 0)} gun once)")
    lines.append('')

    tasks = report.get('tasks', {})
    stale_count = tasks.get('stale_count', 0)
    stale_thresh = tasks.get('stale_days_threshold', 14)
    lines.append(f"[Hareketsiz Gorevler] (>{stale_thresh} gun)")
    lines.append(f"  Acik gorev: {tasks.get('open_count', 0)}, Hareketsiz: {stale_count}")
    for t in tasks.get('stale_tasks', [])[:5]:
        title = _strip_terminal_controls(t.get('title', ''))
        lines.append(f"  - {t.get('path')}: {title} ({t.get('age_days', 0)} gun once)")
    if stale_count > 5:
        lines.append(f"  ... ve {stale_count - 5} gorev daha")
    lines.append('')

    digest = report.get('digest', {})
    digest_days = digest.get('digest_days', 7)
    digest_count = digest.get('count', 0)
    lines.append(f"[Bilgi ve Karar Ozeti] (son {digest_days} gun)")
    lines.append(f"  Uretilen/guncellenen not: {digest_count}")
    for k in digest.get('items', [])[:5]:
        title = _strip_terminal_controls(k.get('title', ''))
        lines.append(f"  - {k.get('path')}: {title}")
    if digest_count > 5:
        lines.append(f"  ... ve {digest_count - 5} not daha")
    lines.append('')

    comp = report.get('companion', {})
    lines.append('[Eslikci ve Akis]')
    lines.append(f"  Kurallar: {comp.get('rules_count', 0)} kural")
    lines.append(f"  Acik is parcaciklari: {comp.get('active_threads', 0)} thread")
    if comp.get('last_session'):
        lines.append(f"  Son oturum: {comp.get('last_session')}")
    if comp.get('active_presence', 0) > 0:
        lines.append(f"  Aktif diger cihaz oturumlari: {comp.get('active_presence')}")
    lines.append('')

    recs = report.get('recommendations', [])
    if recs:
        lines.append('[Sindirim Onerileri]')
        for i, r in enumerate(recs, 1):
            lines.append(f"  {i}. {r}")

    return '\n'.join(lines)
