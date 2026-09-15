"""Shared vault skills; no third-party packages or global skill imports."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid


def _tree(path, vault):
    if not path.resolve().is_relative_to(vault):
        raise ValueError('skill escapes vault')
    if not path.is_dir() or not (path / 'SKILL.md').is_file():
        raise ValueError('skill must contain SKILL.md')
    digest = hashlib.sha256()
    for p in sorted(path.rglob('*')):
        if p.is_symlink():
            raise ValueError('nested skill symlink requires manual review')
        if p.is_file():
            digest.update(p.relative_to(path).as_posix().encode());digest.update(b'\0');digest.update(p.read_bytes())
    return digest.hexdigest()


def _copy(source, target, expected, vault, source_root=None):
    if target.exists() and _tree(target, vault) != expected:
        raise ValueError('skill changed concurrently')
    stage = Path(tempfile.mkdtemp(prefix='.v3-skill-', dir=target.parent))
    try:
        shutil.copytree(source, stage, dirs_exist_ok=True)
        if _tree(stage, vault) != _tree(source, source_root or vault):
            raise ValueError('source changed during copy')
        if target.exists():
            if target.is_symlink() or _tree(target, vault) != expected:
                raise ValueError('skill changed concurrently')
            backup = target.parent / ('.v3-backup-' + target.name + '-' + uuid.uuid4().hex)
            target.rename(backup)  # Preserved reversible original, never discarded.
            try: stage.rename(target)
            except BaseException:
                backup.rename(target);raise
        else: stage.rename(target)
    finally:
        if stage.exists():shutil.rmtree(stage)


def sync_skills(vault, state, mode=None):
    vault=Path(vault).resolve();state=Path(state).resolve()
    if state.is_relative_to(vault):raise ValueError('skill state must be outside vault')
    mode=mode or ('copy' if os.name=='nt' else 'symlink')
    if mode not in ('copy','symlink'):raise ValueError('invalid skill mode')
    state.mkdir(parents=True,exist_ok=True)
    left=vault/'.agents/skills';right=vault/'.claude/skills'
    for p in (left,right):
        if not p.resolve().is_relative_to(vault):raise ValueError('skill root escapes vault')
        p.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(state/'skills.sqlite3',timeout=10)
    result={'synced':[],'conflicts':[],'mode':mode}
    try:
        db.execute('CREATE TABLE IF NOT EXISTS skills(name TEXT PRIMARY KEY, hash TEXT NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        names=sorted({p.name for root in (left,right) for p in root.iterdir() if not p.name.startswith('.')})
        for name in names:
            a=left/name;b=right/name
            try:
                ah=_tree(a,vault) if a.exists() or a.is_symlink() else None
                bh=_tree(b,vault) if b.exists() or b.is_symlink() else None
                old=db.execute('SELECT hash FROM skills WHERE name=?',(name,)).fetchone()
                previous=old[0] if old else None
                if ah and bh and a.resolve()==b.resolve():h=ah
                elif ah==bh:h=ah
                elif not ah or not bh:
                    if previous:raise ValueError('one-sided removal requires review')
                    source,target=(a,b) if ah else (b,a)
                    if target==b and mode=='symlink':
                        try:target.symlink_to(os.path.relpath(source,target.parent),target_is_directory=True)
                        except OSError:_copy(source,target,None,vault)
                    else:_copy(source,target,None,vault)
                    h=ah or bh
                elif previous==ah and previous!=bh:
                    _copy(b,a,ah,vault);h=bh
                elif previous==bh and previous!=ah:
                    _copy(a,b,bh,vault);h=ah
                else:raise ValueError('both skill versions changed')
                if h:
                    db.execute('INSERT OR REPLACE INTO skills VALUES (?,?)',(name,h));result['synced'].append(name)
            except (ValueError,OSError):result['conflicts'].append(name)
        db.commit()
    finally:db.close()
    return result


def import_skill(vault, state, source, name=None, mode=None):
    """Copy only an explicitly selected skill; never scan global skill stores."""
    vault=Path(vault).resolve();source=Path(source).expanduser().resolve()
    name=name or source.name
    if not name or name.startswith('.') or '/' in name or '\\' in name or name in ('.','..'):
        raise ValueError('invalid skill name')
    _tree(source,source)  # Reject all nested symlinks before importing assets.
    target=vault/'.agents/skills'/name
    if not target.parent.resolve().is_relative_to(vault):raise ValueError('skill root escapes vault')
    if target.exists() or target.is_symlink():raise ValueError('skill name already exists')
    other=vault/'.claude/skills'/name
    if other.exists() or other.is_symlink():raise ValueError('skill name already exists in Claude')
    target.parent.mkdir(parents=True,exist_ok=True)
    _copy(source,target,None,vault,source_root=source)
    return sync_skills(vault,state,mode=mode)
