"""Read-only doctor reports ported from MrMerkus/MMS: boundary and closed tasks.

Reads files and directories only: no model call, no network, and no write
anywhere — these scans are doctor-only and doctor must stay read-only. The
done-task sweep reports; V3 stores record identity in the runtime database by
source path, so moving a source out from under a record would orphan its
history — that is why there is no automatic move here (MMS kapanis.sh moves
because its vault has no index). Human lines are ASCII Turkish, matching the
other modules.

Unicode care: folder and file names in a real vault are Turkish ("Arşiv",
"Şifre", "MÜŞTERİLER"), may carry an emoji or number prefix, and can arrive
NFD-encoded from macOS or iCloud. Names are folded (NFC, Turkish İ/ı, ASCII)
before any word match so a rule cannot silently stop applying on a real
folder name.
"""
import json
import os
from pathlib import Path
import re
import time
import unicodedata

# Kasa-class folders: personal or financial content that must never reach the
# session context through the hygiene channels. The MMS vault answered this with
# a dedicated 🔐 kasa/ folder its loader never opens; a V3 vault has no such
# folder, so the same guarantee is enforced by name and by finding: any
# top-level folder whose name carries one of these words is reported in
# boundary() so the owner knows which folders the guarantee names.
#
# Matching is word-based on a folded name, not an anchored regex over the raw
# name: real folders are "🔐 Kasa", "410-Şifreler", "MÜŞTERİLER" or arrive NFD
# from macOS/iCloud, and none of those matched `^(şifre|...)$`. Python's
# re.IGNORECASE does not fold Turkish İ/ı either, so the name is folded first.
# Archives are not kasa-class: they are quiet by design, not private, and the
# template ships "📦 900-Archive".
SENSITIVE_WORDS = re.compile(
    r'(?:kasa|sifre|parola|kimlik|kimlig|finans|finansal|musteri|vergi|fatura|maas|ozel|gizli|gizlilik)'
    r'(?:ler|lar)?(?:i|im|in|imiz|leri|lari)?'
    r'|(?:private|secret|password|credential)s?')
_TR_FOLD = str.maketrans({'ş': 's', 'ğ': 'g', 'ü': 'u', 'ö': 'o', 'ç': 'c', 'ı': 'i', 'â': 'a', 'î': 'i', 'û': 'u'})
TERMINAL_STATUSES = {'done', 'cancelled', 'kapandi'}
# Directories a boundary walk must never descend into: they are the finding, not the vault.
CODE_DIRS = {'node_modules', 'venv', '.venv', '__pycache__'}
WALK_LIMIT = 20000  # directories; a doctor report must stay bounded on any vault


def fold(name):
    """NFC, Turkish-aware casefold and ASCII-fold a name: 'MÜŞTERİLER' and NFD 'Şifre' both fold."""
    text = unicodedata.normalize('NFC', str(name)).replace('İ', 'i').replace('I', 'i').lower()
    return unicodedata.normalize('NFC', text.replace('\u0307', '')).translate(_TR_FOLD)


def sensitive_excluded(name):
    """True when a top-level folder name carries a kasa-class word (any position, any case/normal form)."""
    return any(SENSITIVE_WORDS.fullmatch(word) for word in re.findall(r'[^\W\d_]+', fold(name)))


def _front_status(text):
    """The frontmatter status, folded, from JSON (what V3 writes) or flat YAML frontmatter; else None."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != '---':
        return None
    end = next((index for index in range(1, len(lines)) if lines[index].strip() == '---'), None)
    if end is None:
        return None
    header = '\n'.join(lines[1:end]).strip()
    if header.startswith('{'):
        try:
            value = json.loads(header).get('status')
        except (ValueError, AttributeError):
            return None
        return fold(value).strip() if isinstance(value, str) else None
    for line in lines[1:end]:
        match = re.fullmatch(r'status:[ \t]*(["\']?)([^"\'#]*?)\1[ \t]*(?:#.*)?', line.rstrip())
        if match:
            return fold(match[2]).strip()
    return None


def boundary(vault):
    """Repository and vault-root boundary checks; information for the doctor.

    The MMS denetci guards four invariants here: one code root inside the vault
    (node_modules / venv), one nested second repo, an Obsidian index above or
    below the root, and privacy-facing leftovers. Each check reads only paths.
    The kasa check reports the sensitive folders the hygiene scans already
    exclude, naming the active guarantee instead of leaving it implicit.
    """
    vault = Path(vault).resolve()
    report = {'status': 'ok', 'findings': [], 'sensitive_excluded': [], 'code_dirs': [],
              'nested_repositories': [], 'backup_artifacts': [], 'walk_truncated': False}
    top = sorted(vault.iterdir(), key=lambda entry: entry.name)
    kasa = [entry.name for entry in top
            if entry.is_dir() and not entry.is_symlink() and not entry.name.startswith('.')
            and sensitive_excluded(entry.name)]
    if kasa:
        report['sensitive_excluded'] = kasa
        report['findings'].append('kasa_excluded: ' + ', '.join(kasa) +
                                  '; hygiene scans skip these folders, automatic context still follows'
                                  ' visibility metadata - mark their sources visibility: private for the full guarantee.')
    parent = vault.parent
    if (parent / '.obsidian').is_dir():
        report['findings'].append('parent_obsidian_index: parent directory also holds a .obsidian vault root; '
                                  'Obsidian could open the parent and treat this folder as a subfolder.')
    if not (vault / '.obsidian').is_dir():
        report['findings'].append('no_root_obsidian: vault root has no .obsidian; open this exact folder in Obsidian, '
                                  'not a parent.')
    nested, code, visited = [], [], 0
    for directory, folders, files in os.walk(vault):
        visited += 1
        relative_dir = Path(directory).relative_to(vault).as_posix()
        if visited > WALK_LIMIT:
            report['walk_truncated'] = True
            folders[:] = []
            break
        if relative_dir != '.' and ('.git' in folders or '.git' in files):
            # A .git file is a worktree or submodule link: still a second repository here.
            # Its tree belongs to that repository, so the walk stops at its root.
            nested.append(relative_dir)
            folders[:] = []
            continue
        for name in folders:
            if name in CODE_DIRS:
                code.append(name if relative_dir == '.' else relative_dir + '/' + name)
        # Never descend into hidden folders or code trees: they are the finding, and a
        # node_modules walk would cost the doctor its latency on exactly the vault it warns about.
        folders[:] = [name for name in folders if not name.startswith('.') and name not in CODE_DIRS
                      and relative_dir.count('/') < 6]
    if code:
        report['code_dirs'] = sorted(code)
        report['findings'].append('code_inside_vault: ' + ', '.join(report['code_dirs'][:5]) +
                                  '; keep the code repo outside the memory vault.')
    if nested:
        report['nested_repositories'] = sorted(nested)
        report['findings'].append('nested_git_repository: ' + ', '.join(report['nested_repositories'][:3]) +
                                  '; a subfolder is its own git repository inside the vault.')
    names = {entry.name for entry in top}
    leftovers = []
    for entry in top:
        if not entry.is_file() or entry.is_symlink():
            continue
        # A sync conflict copy ("Plan 2.md") counts only beside its original ("Plan.md");
        # a note that merely ends in a number is not a leftover.
        copy = re.fullmatch(r'(.+) \d{1,2}(\.md)', entry.name)
        if entry.name.endswith(('.bak', '.orig', '.yedek')) or (copy and copy[1] + copy[2] in names):
            leftovers.append(entry.name)
    if leftovers:
        report['backup_artifacts'] = leftovers
        report['findings'].append('backup_artifacts: ' + ', '.join(leftovers[:5]) +
                                  '; duplicate editor or sync copies may carry a private copy.')
    if report['findings']:
        report['status'] = 'attention'  # information only; doctor status is raised by sync, not here
    return report


def closed_tasks(vault, days=30, limit=20, now=None):
    """Closed work that no longer belongs at the top level - a report, not a move.

    Scans task sources under tasks/ for a done/cancelled (or kapandi) frontmatter
    status, older than the number of days by file mtime (metadata carries
    updated_at only when the writer set it, so mtime is the independent bound).
    The status is read from the frontmatter only: V3 itself writes JSON
    frontmatter (`"status": "done"`), Obsidian writes flat YAML, and a body line
    that happens to start with "status: done" is not a task status. V3 keeps
    source paths in the runtime database; a kapanis move would sever every
    receipt ref and revision history, so nothing here moves or writes a file.
    Lists the oldest first.
    """
    vault = Path(vault).resolve()
    now = time.time() if now is None else now
    cutoff = now - days * 86400
    closed = []
    folder = vault / 'tasks'
    if not folder.is_dir() or folder.is_symlink():
        return {'closed_count': 0, 'closed': [], 'truncated': False, 'days': days}
    for directory, folders, files in os.walk(folder):
        folders[:] = sorted(name for name in folders if not name.startswith('.'))
        for name in sorted(files):
            path = Path(directory) / name
            if not name.endswith('.md') or name.startswith('.') or path.is_symlink():
                continue
            try:
                modified = path.stat().st_mtime
                if modified > cutoff:
                    continue
                text = path.read_text(encoding='utf-8', errors='replace')
            except (OSError, ValueError):
                continue
            if _front_status(text) not in TERMINAL_STATUSES:
                continue
            closed.append({'source': path.relative_to(vault).as_posix(),
                           'days_old': int((now - modified) // 86400)})
    closed.sort(key=lambda entry: (-entry['days_old'], entry['source']))
    return {'closed_count': len(closed), 'closed': closed[:limit], 'truncated': len(closed) > limit,
            'days': days}
