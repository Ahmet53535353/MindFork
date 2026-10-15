#!/usr/bin/env python3
"""Measure an upstream merge before touching the working tree.

A merge is the one operation where a confident-sounding wrong number is most
expensive: `git merge-tree` on 2026-09-27 refuted a hand-made estimate of five
conflicts by reporting one. This script exists so the conflict set is never
estimated again. It reports only; it never edits, merges, or resolves.

Three reports, each answering a question that has already cost a merge:

  preflight  Is the remote-tracking state trustworthy? A refspec that tracks one
             branch makes `origin/main` stale, and `--force-with-lease` then
             rejects every push with "stale info" while the local ref disagrees
             with the server. Silent, and the cost only shows up as a failed push.
  merge      How far behind are we, and which files actually conflict?
  coverage   Which of our own fixes has a test that would notice a merge
             dropping it? Coverage is measured by behaviour marker, never by
             symbol name -- a grep for the symbol says nothing about whether the
             behaviour survives.

Usage:
    python3 measure_merge.py                # all three
    python3 measure_merge.py --only merge
    python3 measure_merge.py --theirs <ref>  # dry-run against an arbitrary ref
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DIVERGENCES = Path(__file__).resolve().parent / 'divergences.md'
CONFLICT_RE = re.compile(r'^CONFLICT \([^)]*\): Merge conflict in (.+)$', re.M)


def run(*args: str, check: bool = False) -> subprocess.CompletedProcess:
    """Run git with a fixed locale so its messages are parseable everywhere."""
    env = {**os.environ, 'LC_ALL': 'C', 'GIT_PAGER': 'cat'}
    done = subprocess.run(('git',) + args, capture_output=True, text=True, env=env, cwd=ROOT)
    if check and done.returncode != 0:
        raise SystemExit(f'git {" ".join(args)} failed:\n{done.stderr.strip()}')
    return done


# --- preflight -------------------------------------------------------------

def preflight() -> bool:
    """Refspec health. Both remotes must track every branch, not a selection."""
    print('PREFLIGHT')
    ok = True
    for remote in ('origin', 'upstream'):
        spec = run('config', '--get-all', f'remote.{remote}.fetch').stdout.split()
        wildcard = any(s.startswith('+refs/heads/*') for s in spec)
        print(f'  {remote:<9} refspec {"ok (+refs/heads/*)" if wildcard else "KISITLI"}')
        if not wildcard:
            print(f'            gerçek: {spec or "(yok)"}')
            print(f'            düzelt : git config --add remote.{remote}.fetch '
                  f"'+refs/heads/*:refs/remotes/{remote}/*'")
            ok = False
    return ok


# --- merge state -----------------------------------------------------------

def behind(theirs: str) -> int | None:
    """Commits in `theirs` that HEAD does not have.

    Direction matters: `base..HEAD` counts *our* commits and reads as "behind"
    while reporting the opposite truth. A merge that reports 80 behind when it
    is level is worse than no report, because it invites work that is not there.
    """
    if run('merge-base', '--is-ancestor', 'HEAD', theirs).returncode == 0:
        return 0
    return len(run('rev-list', f'HEAD..{theirs}').stdout.split())


_TREE: dict[str, str | None] = {}


def merge_tree(theirs: str) -> str | None:
    """Result tree of the real three-way merge, or None when it is clean.

    Kept because the tree also carries each conflicted file's
    merged-with-markers blob, which is where a per-file hunk count comes from.
    """
    if theirs not in _TREE:
        done = run('merge-tree', '--write-tree', '--name-only', 'HEAD', theirs)
        head = done.stdout.strip().split('\n', 1)[0].strip() if done.stdout.strip() else ''
        _TREE[theirs] = head if done.returncode != 0 and head else None
    return _TREE[theirs]


def conflicts(theirs: str) -> list[str]:
    """Conflicted paths from a real three-way computation, never an estimate.

    `--name-only` lists every path in the result tree, conflicted or not, so the
    CONFLICT lines are the only authoritative source. They are localised, hence
    LC_ALL=C in run().
    """
    if merge_tree(theirs) is None:
        return []
    done = run('merge-tree', '--write-tree', '--name-only', 'HEAD', theirs)
    return sorted({line.strip() for line in CONFLICT_RE.findall(done.stdout)})


def nature(theirs: str, path: str) -> tuple[int, int, int]:
    """(hunks, ours_lines, theirs_lines) for one conflicted file.

    The hunk count comes from the conflicted blob in the result tree, not from
    the human-readable merge-tree form: that form concatenates every file's diff,
    so counting its markers counts all files at once and reported three hunks for
    a file with one.
    """
    tree = merge_tree(theirs)
    if tree is None:
        return (0, 0, 0)
    merged = run('show', f'{tree}:{path}')
    hunks = len(re.findall(r'^<<<<<<< ', merged.stdout, re.M))
    ours = run('show', f'HEAD:{path}')
    theirs_text = run('show', f'{theirs}:{path}')
    return (hunks, len(ours.stdout.splitlines()), len(theirs_text.stdout.splitlines()))


def report_merge(theirs: str) -> bool:
    count = behind(theirs)
    if count is None:
        print(f'MERGE\n  {theirs} okunamadı — merge-base yok, muhtemelen ilişkisiz ref')
        return False
    if count == 0:
        print(f'MERGE\n  {theirs} ile eşitiz (behind 0). Yapılacak bir şey yok.')
        return True
    print(f'MERGE\n  behind: {count} commit')
    files = conflicts(theirs)
    if not files:
        print('  merge-tree: çakışma yok (otomatik birleşecek)')
        return True
    print(f'  merge-tree: {len(files)} dosyada çakışma')
    for path in files:
        hunks, ours, theirs_lines = nature(theirs, path)
        print(f'    {hunks:>3} hunk  biz {ours:>5} / onlar {theirs_lines:>5}  {path}')
    print('\n  Bu liste tahmin değil, merge-tree sonucudur. Elle sayma.')
    return True


# --- coverage --------------------------------------------------------------

def coverage() -> bool:
    """Which local fixes have a test that would notice their disappearance.

    Keyed on the behaviour marker, not the symbol: on 2026-10-15 a grep for
    `VALID_MEMORY_TYPES` found zero tests and looked like a gap, while six test
    files covered the gate it implements. The gap that was real -- a guard with
    no test for 14 days -- was found by reading history, not by grepping.
    """
    if not DIVERGENCES.is_file():
        print('COVERAGE\n  divergences.md yok — kapsama raporu atlandı')
        return False
    rows = []
    for line in DIVERGENCES.read_text(encoding='utf-8').split('\n'):
        if not line.startswith('|') or line.count('|') < 4:
            continue
        cells = [c.strip().strip('`') for c in line.strip('|').split('|')]
        if len(cells) < 3 or cells[0] in ('düzeltme',) or set(cells[0]) <= set('-: '):
            continue
        rows.append(cells)
    if not rows:
        print('COVERAGE\n  divergences.md ayrıştırılamadı')
        return False
    tests = list((ROOT / 'tests').rglob('*.py'))
    print('COVERAGE')
    complete = True
    for cells in rows:
        name, marker = cells[0], cells[1]
        hits = sorted({f'tests/{p.relative_to(ROOT / "tests")}' for p in tests
                       if marker in p.read_text(encoding='utf-8', errors='replace')})
        mark = 'ok ' if hits else 'YOK'
        if not hits:
            complete = False
        print(f'  {mark} {name:<34} {len(hits)} test dosyası  ({marker})')
        if not hits:
            print('       → bu düzeltme merge\'de sessizce düşebilir: test yaz ya da kabul et')
    return complete


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--theirs', default='upstream/main', help='upstream ref (default upstream/main)')
    parser.add_argument('--only', choices=('preflight', 'merge', 'coverage'), action='append')
    args = parser.parse_args()
    steps = args.only or ['preflight', 'merge', 'coverage']
    ok = True
    if 'preflight' in steps:
        ok &= preflight()
    if 'merge' in steps:
        ok &= report_merge(args.theirs)
    if 'coverage' in steps:
        coverage()
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())