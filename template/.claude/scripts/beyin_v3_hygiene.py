"""Read-only doctor reports ported from MrMerkus/MMS: boundary and closed tasks.

Reads files and directories only: no model call, no network, and no write
anywhere — these scans are doctor-only and doctor must stay read-only. The
done-task sweep reports; V3 stores record identity in the runtime database by
source path, so moving a source out from under a record would orphan its
history — that is why there is no automatic move here (MMS kapanis.sh moves
because its vault has no index). Human lines are ASCII Turkish, matching the
other modules.

Unicode care: folder and file names in a real vault are Turkish ("Arşiv",
"Şifre", "Müşteriler"). Every name-facing pattern below matches both the
ASCII spelling and the Turkish-diacritic spelling so a rule cannot silently
stop applying on a renamed folder.
"""
import os
from pathlib import Path
import re
import time

# Kasa-class folders: personal or financial content that must never reach the
# session context through the hygiene channels. The MMS vault answered this with
# a dedicated 🔐 kasa/ folder its loader never opens; a V3 vault has no such
# folder, so the same guarantee is enforced by name and by finding: any
# top-level folder matching this pattern is skipped here and reported in
# boundary() so the owner knows the guarantee is active.
SENSITIVE_DIRS = re.compile(
    r'(?ix)^(kasa|s[iı]fre|ş[iı]fre|kimlik|kimlikler|finans|finansal|'
    r'm[uü]şteri|m[uü]şteriler|vergi|fatura|maaş|maşlar|maaşlar|'
    r'arşiv|arsiv|archive|[öo]zel|gizli|gizlilik|private|secret)$')
STATUS = re.compile(r'(?mi)^status:[ \t]*(done|kapandi|kapandı|cancelled)')


def sensitive_excluded(name):
    """True when a top-level folder name is kasa-class and must stay out of every hygiene scan."""
    return bool(SENSITIVE_DIRS.match(name))


def boundary(vault):
    """Repository and vault-root boundary checks; information for the doctor.

    The MMS denetci guards four invariants here: one code root inside the vault
    (node_modules / venv), one nested second repo, an Obsidian index above or
    below the root, and privacy-facing leftovers. Each check reads only paths.
    The kasa check reports the sensitive folders the hygiene scans already
    exclude, naming the active guarantee instead of leaving it implicit.
    """
    vault = Path(vault).resolve()
    report = {'status': 'ok', 'findings': [], 'sensitive_excluded': []}
    kasa = sorted(entry.name for entry in vault.iterdir()
                  if entry.is_dir() and not entry.is_symlink() and not entry.name.startswith('.')
                  and sensitive_excluded(entry.name))
    if kasa:
        report['sensitive_excluded'] = kasa
        report['findings'].append('kasa_excluded: ' + ', '.join(kasa) +
                                  '; these folders are skipped by every hygiene scan, the'
                                  ' context scans (strict matching) still follow visibility metadata -'
                                  ' mark their sources visibility: private for the full guarantee.')
    parent = vault.parent
    if (parent / '.obsidian').is_dir():
        report['findings'].append('parent_obsidian_index: parent directory also holds a .obsidian vault root; '
                                  'Obsidian could open the parent and treat this folder as a subfolder.')
    if not (vault / '.obsidian').is_dir():
        report['findings'].append('no_root_obsidian: vault root has no .obsidian; open this exact folder in Obsidian, '
                                  'not a parent.')
    code = [entry.name for entry in vault.iterdir()
            if entry.is_dir() and not entry.is_symlink() and entry.name in ('node_modules', 'venv', '.venv')]
    if code:
        report['findings'].append('code_inside_vault: ' + ', '.join(sorted(code)) +
                                  '; keep the code repo outside the memory vault.')
    nested = []
    for directory, folders, files in os.walk(vault):
        depth = 1 + directory[len(str(vault)):].count(os.sep)
        if depth > 6:
            folders[:] = []
            continue
        folders[:] = [name for name in folders if not name.startswith('.') or name == ('.git',)[0]]
        if '.git' in folders and directory != str(vault):
            relative = Path(directory).relative_to(vault).as_posix()
            nested.append(relative)
            folders.remove('.git')
    if nested:
        report['findings'].append('nested_git_repository: ' + ', '.join(nested[:3]) +
                                  '; a subfolder is its own git repository inside the vault.')
    leftovers = [entry.name for entry in vault.iterdir()
                 if entry.is_file() and not entry.is_symlink() and (
                     entry.name.endswith(('.bak', '.orig', '.yedek')) or
                     re.match(r'^\d\.md', entry.name))]
    if leftovers:
        report['findings'].append('backup_artifacts: ' + ', '.join(sorted(leftovers)[:5]) +
                                  '; duplicate editor or sync copies may carry a private copy.')
    if report['findings']:
        report['status'] = 'attention'  # information only; doctor status is raised by sync, not here
    return report


def closed_tasks(vault, days=30, limit=20, now=None):
    """Closed work that no longer belongs at the top level - a report, not a move.

    Scans tasks/*.md frontmatter for status done/kapandi, older than the number
    of days by file mtime (metadata carries updated_at only when the writer set
    it, so mtime is the independent bound). V3 keeps source paths in the runtime
    database; a kapanis move would sever every receipt ref and revision history,
    so the decision stays with the user. Lists the oldest first.
    """
    vault = Path(vault).resolve()
    now = time.time() if now is None else now
    cutoff = now - days * 86400
    closed = []
    folder = vault / 'tasks'
    if not folder.is_dir():
        return {'closed_count': 0, 'closed': [], 'truncated': False}
    for path in sorted(folder.glob('*.md')):
        if path.is_symlink():
            continue
        try:
            text = path.read_text(encoding='utf-8', errors='replace')
        except (OSError, ValueError):
            continue
        if not STATUS.search(text):
            continue
        try:
            modified = path.stat().st_mtime
        except OSError:
            continue
        if modified > cutoff:
            continue
        closed.append({'source': path.relative_to(vault).as_posix(),
                       'days_old': int((now - modified) // 86400)})
    closed.sort(key=lambda entry: (-entry['days_old'], entry['source']))
    return {'closed_count': len(closed), 'closed': closed[:limit], 'truncated': len(closed) > limit,
            'days': days}
