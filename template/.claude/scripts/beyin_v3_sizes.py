"""Size inventory for the vault: notes, generated files, and index budgets.

Read-only measurement. Reports what exceeds the character cap; never rewrites
a source file. The companion hygiene module supplies per-file budgets, and
the shared note cap applies everywhere else.
"""
from pathlib import Path

NOTE_CAP_CHARS = 12000
NOTE_TREES = ('knowledge', 'notes')
SIZE_CHECKED = ('knowledge/index.md', 'knowledge/log.md', 'knowledge/v3/outcomes.md')
GENERATED_GLOBS = ('daily/v3/*.md',)

PROJECTION_GUARD = ('knowledge/index.md', 'knowledge/log.md')


def is_generated(relative):
    return (relative.startswith('knowledge/v3/')
            or relative in PROJECTION_GUARD
            or relative.startswith('daily/v3/'))


def _note_files(vault):
    root = Path(vault)
    files = []
    for tree in NOTE_TREES:
        base = root / tree
        if base.is_dir():
            files.extend(sorted(path for path in base.rglob('*.md') if path.is_file()))
    return files


def inventory(vault, limits=None, extra=()):
    caps = dict(limits or {})
    files = _note_files(vault)
    oversize = []

    def entry_for(relative, chars):
        cap = caps.get(relative)
        if chars > NOTE_CAP_CHARS or (cap is not None and chars > cap):
            limit = cap if cap is not None else NOTE_CAP_CHARS
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
