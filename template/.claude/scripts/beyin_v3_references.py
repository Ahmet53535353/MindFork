"""Report in-vault links in instruction and skill files that resolve to nothing.

Reads files only: no model call, no network, no write. Code (fenced blocks and inline spans) is
skipped so examples in skills never count, and a link that leaves the vault is not ours to judge.
"""
import os
from pathlib import Path
import re
from urllib.parse import unquote

FENCE = re.compile(r'(?ms)^[ \t]*(```|~~~).*?^[ \t]*\1[^\n]*$')
INLINE = re.compile(r'`[^`\n]*`')
WIKI = re.compile(r'!?\[\[([^\]\n]+)\]\]')
LINK = re.compile(r'!?\[[^\]\n]*\]\((<[^>\n]+>|[^)\s]+)(?:\s+"[^"\n]*")?\)')
SCHEME = re.compile(r'^[A-Za-z][A-Za-z0-9+.-]*:')
PLACEHOLDER = set('<>{}*$')
LIMIT = 20


def instruction_files(vault):
    """AGENTS.md, CLAUDE.md, the companion Kurallar.md and every Markdown file in the skill roots."""
    files = [vault / 'AGENTS.md', vault / 'CLAUDE.md']
    try:
        import beyin_v3_companion
        folder = beyin_v3_companion.directory(vault)
        if folder is not None:
            files.append(folder / 'Kurallar.md')
    except Exception:
        pass  # a missing companion never hides the other files
    for root in ('.agents/skills', '.claude/skills'):
        if (vault / root).is_dir():
            files += sorted((vault / root).rglob('*.md'))
    return [path for path in dict.fromkeys(files) if path.is_file()]


def _note_index(vault):
    """Lower-cased file names and stems outside hidden folders, as Obsidian resolves a bare [[name]]."""
    names = set()
    for directory, folders, files in os.walk(vault):
        folders[:] = [name for name in folders if not name.startswith('.')]
        for name in files:
            names.add(name.casefold())
            if name.casefold().endswith('.md'):
                names.add(name[:-3].casefold())
    return names


def _blank_code(text):
    """Blank code while keeping every newline, so reported line numbers stay true."""
    text = FENCE.sub(lambda match: '\n' * match.group(0).count('\n'), text)
    return INLINE.sub(lambda match: ' ' * len(match.group(0)), text)


def _inside(vault, path):
    try:
        path.resolve().relative_to(vault)
        return True
    except ValueError:
        return False


def _exists(path):
    return path.exists() or (not path.suffix and path.with_name(path.name + '.md').exists())


def _wiki_dead(vault, source, target, index):
    target = target.split('|', 1)[0].rstrip('\\').split('#', 1)[0].split('^', 1)[0].strip()
    if not target or PLACEHOLDER & set(target):
        return None
    if '/' in target:
        candidates = [vault / target.lstrip('/'), source.parent / target]
        candidates = [path for path in candidates if _inside(vault, path)]
        return None if not candidates or any(_exists(path) for path in candidates) else target
    return None if target.casefold() in index or _exists(source.parent / target) else target


def _link_dead(vault, source, target):
    target = unquote(target.strip('<>')).split('#', 1)[0].split('?', 1)[0].strip()
    if not target or SCHEME.match(target) or target.startswith('//') or PLACEHOLDER & set(target):
        return None
    path = vault / target.lstrip('/') if target.startswith('/') else source.parent / target
    if not _inside(vault, path):
        return None
    return None if _exists(path) else target


def check(vault):
    vault = Path(vault).resolve()
    files = instruction_files(vault)
    dead, index = [], None
    for source in files:
        try:
            text = _blank_code(source.read_text(encoding='utf-8-sig'))
        except (OSError, UnicodeError):
            continue
        for number, line in enumerate(text.splitlines(), 1):
            found = []
            for match in WIKI.finditer(line):
                if index is None:
                    index = _note_index(vault)
                found.append(_wiki_dead(vault, source, match.group(1), index))
            found += [_link_dead(vault, source, match.group(1)) for match in LINK.finditer(line)]
            dead += [{'file': source.relative_to(vault).as_posix(), 'line': number, 'target': target}
                     for target in found if target]
    return {'checked_files': len(files), 'dead_count': len(dead), 'dead': dead[:LIMIT],
            'truncated': len(dead) > LIMIT}
