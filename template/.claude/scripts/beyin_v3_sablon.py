"""Name-addressed template lookup: `beyin.py sablon <ad>`.

A template in `📋 Templates/` is a procedure the agent follows, not a note it retrieves. Its
whole value is the guarantee that the *named* procedure was the one opened, so this module
fails loudly instead of opening whatever resembles the name: a wrong guess at a template
becomes a wrong action, and an action on the outside (an issue that stays open) cannot be
undone by rewriting the file.

The folder is found by its generic product words, like the hygiene scans already do, so a
personal vault layout never enters the code.
"""
import re
import unicodedata
from pathlib import Path

TEMPLATE_WORDS = re.compile(r'(?:templates?|sablon|sablonlar|şablon|şablonlar)')


def _fold(text):
    """Compare names the way the hygiene scans and project scopes already do."""
    return unicodedata.normalize('NFC', str(text)).casefold()


def template_dir(vault):
    """The vault's template folder, or None. Ambiguity (two such folders) is not a guess."""
    try:
        entries = sorted(Path(vault).iterdir())
    except OSError:
        return None
    found = [entry for entry in entries
             if entry.is_dir() and not entry.is_symlink() and not entry.name.startswith('.')
             and TEMPLATE_WORDS.search(_fold(entry.name))]
    return found[0] if len(found) == 1 else None


def available(vault):
    """Template names, stem only: the `.md` is storage, the name is what anyone says."""
    folder = template_dir(vault)
    if folder is None:
        return []
    return sorted(path.stem for path in folder.glob('*.md'))


def _key(text):
    """Fold a spoken name to its letters: 'GitHub Issue', 'github_issue', 'githubissue' are one."""
    return re.sub(r'[^0-9a-z]', '', _fold(text).replace('ı', 'i').replace('ş', 's')
                  .replace('ğ', 'g').replace('ü', 'u').replace('ö', 'o').replace('ç', 'c'))


def _resolve(names, spoken):
    """Folded exact match only. A containment match would let "issue" open "GithubIssue" and
    "bug" open "BugReport" -- the wrong instruction, applied for real. Refusing costs one turn;
    guessing costs an action nobody can undo, so near misses are listed, not resolved."""
    wanted = _key(spoken)
    if not wanted:
        return None
    for name in names:
        if _key(name) == wanted:
            return name
    return None


def run(vault, name=None):
    """List the templates, or return one whole. Never a truncated body: the body is the
    instruction being followed, and a half template is a half action.

    A refusal raises ValueError, the same channel every other command uses for a caller
    mistake, so the CLI prints one clean message and exits non-zero.
    """
    folder = template_dir(vault)
    if folder is None:
        raise ValueError('Sablon klasoru bulunamadi (📋 Templates).')
    names = available(vault)
    if not name:
        if not names:
            return {'status': 'empty', 'templates': [], 'folder': folder.name}
        return {'status': 'ok', 'templates': names, 'folder': folder.name}
    resolved = _resolve(names, name)
    if resolved is None:
        listing = ', '.join(names) if names else '(klasor bos)'
        raise ValueError(f'"{name}" icin sablon yok. Mevcut templates: {listing}.')
    try:
        content = (folder / (resolved + '.md')).read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(f'Sablon okunamadi: {type(exc).__name__}') from exc
    return {'status': 'ok', 'template': resolved, 'content': content, 'folder': folder.name}