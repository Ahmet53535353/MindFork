#!/usr/bin/env python3
"""Measure an upstream merge before touching the working tree.

A merge is the one operation where a confident-sounding wrong number is most
expensive: `git merge-tree` on 2026-09-27 refuted a hand-made estimate of five
conflicts by reporting one. This script exists so the conflict set is never
estimated again. It reports only; it never edits, merges, or resolves.

Four reports, each answering a question that has already cost a merge:

  preflight  Is the remote-tracking state trustworthy? A refspec that tracks one
             branch makes `origin/main` stale, and `--force-with-lease` then
             rejects every push with "stale info" while the local ref disagrees
             with the server. Silent, and the cost only shows up as a failed push.
  merge      How far behind are we, and which files actually conflict?
  coverage   Which of our own fixes has a test that would notice a merge
             dropping it? Coverage is measured by behaviour marker, never by
             symbol name -- a grep for the symbol says nothing about whether the
             behaviour survives.
  worktree   Which file broke a test? A green suite plus a red test does not say
             whether the test is wrong or we are, and on 2026-10-18 the answer was
             one file out of five candidates: swapping that single file for
             upstream's cut the failures from five to zero, while its two
             neighbours (the file the conflict was in, and the file the theory
             pointed at) changed nothing. Guessing the culprit by reading the
             conflict is how two wrong fixes got written that day.

Usage:
    python3 measure_merge.py                # preflight + merge + coverage
    python3 measure_merge.py --only merge
    python3 measure_merge.py --theirs <ref>  # dry-run against an arbitrary ref
    python3 measure_merge.py --only worktree --test tests/v3_hook_test.py
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
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


# --- worktree lab ----------------------------------------------------------

def _pytest(cwd: Path, target: str) -> tuple[int, str]:
    """(failure count, last line) for one pytest target.

    The count, not pass/fail, is the measure. A whole test file can need two files
    restored to go green, and then no single swap reaches zero -- but it still drops
    from five failures to one, and that drop is the evidence. Pass/fail would have
    reported both rows as FAIL and said nothing.
    """
    env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'utf-8'}
    done = subprocess.run([sys.executable, '-m', 'pytest', target, '-q', '-p', 'no:cacheprovider'],
                          capture_output=True, text=True, cwd=cwd, env=env, timeout=1800)
    tail = (done.stdout + done.stderr).strip().split('\n')
    last = tail[-1] if tail else ''
    if done.returncode in (4, 5) or 'ERROR: file or directory not found' in done.stdout \
            or 'no tests ran' in done.stdout.lower():
        # pytest's usage/no-collection codes are not a red test. Reporting them as zero
        # failures would print "test geçiyor" for a target that never ran.
        return -1, f'HEDEF KOŞMADI ({last})'
    failed = re.search(r'(\d+) failed', done.stdout)
    errors = re.search(r'(\d+) error', done.stdout)
    count = int(failed.group(1)) if failed else (int(errors.group(1)) if errors else 0)
    return count, last


def _candidates(theirs: str, limit: int) -> list[str]:
    """Files where our tree and theirs disagree, runtime first: the culprit is code."""
    changed = [p for p in run('diff', '--name-only', 'HEAD', theirs).stdout.split('\n') if p.strip()]
    order = ('template/.claude/scripts/', 'scripts/', 'tests/', 'template/')
    def rank(path: str) -> int:
        for i, prefix in enumerate(order):
            if path.startswith(prefix):
                return i
        return len(order)
    ranked = sorted(changed, key=lambda p: (rank(p), p))
    if len(ranked) > limit:
        print(f'  ({len(ranked)} aday vardı, {limit} tanesi sınandı; --limit ile artır)')
    return ranked[:limit]


def worktree(theirs: str, target: str, only: list[str] | None, limit: int, keep: bool) -> bool:
    """Find which file turns a red test green, by swapping files one at a time.

    The baseline is upstream's own tree in a throwaway worktree: a test that fails
    there is not ours to fix. When it passes there, every candidate file is
    temporarily replaced by upstream's version in *this* tree and the test is run
    again; the file that makes it pass is the one carrying our behaviour. The
    working tree is restored after every swap and verified at the end, because a
    measurement tool that leaves the tree changed is worse than no tool.

    Only for a single red test. For "the suite is red", read the failure first:
    N failing tests share N causes, and this costs one run per file.
    """
    if not target:
        print('WORKTREE\n  --test gerekli: tek bir kırmızı testin adresini ver')
        return False
    before = run('status', '--porcelain').stdout
    unmerged = {line[3:] for line in before.split('\n') if line[:2] in ('UU', 'AA', 'DU', 'UD', 'AU', 'UA', 'DD')}
    parent = Path(tempfile.mkdtemp(prefix='beyin-merge-lab-'))
    lab = parent / 'theirs'
    print(f'WORKTREE\n  taban: {theirs} -> {lab}')
    added = run('worktree', 'add', '--detach', '--force', str(lab), theirs).returncode == 0
    try:
        if not added:
            print('  worktree açılamadı; elde ölçmek zorundayın')
            return False
        base_fail, base_line = _pytest(lab, target)
        print(f'  taban ({theirs}): {base_fail} hata  {base_line}')
        if base_fail < 0:
            print('  → Hedef upstream ağacında koşmadı (yeni test olabilir); `--files`/`--limit` daralt.')
            return False
        if base_fail:
            print('  → Bu test upstream ağacında da kırık. Merge\'in işi değil; yukarı kaynağı aç.')
            return True
        ours, ours_line = _pytest(ROOT, target)
        print(f'  bizim ağaç:        {ours} hata  {ours_line}')
        if ours < 0:
            print('  → Hedef bizim ağaçta da koşmadı; adresi düzelt.')
            return False
        if not ours:
            print('  → Test geçiyor; ölçülecek kırılma yok.')
            return True
        candidates = only or _candidates(theirs, limit)
        rows = []
        for path in candidates:
            if path in unmerged:
                print(f'    atla (çakışmalı) {path}')
                continue
            local = ROOT / path
            if not local.is_file():
                continue
            blob = run('show', f'{theirs}:{path}')
            if blob.returncode != 0:
                continue
            original = local.read_bytes()
            try:
                local.write_bytes(blob.stdout.encode('utf-8'))
                fail, _ = _pytest(ROOT, target)
            finally:
                local.write_bytes(original)
            if fail < 0:
                print(f'    ---  koşmadı           {path}')
                continue
            rows.append((path, fail))
            print(f'    {fail:>3} hata (bizim {ours})  {path}')
        drops = [p for p, f in rows if f < ours]
        print(f'\n  Hata sayısını düşüren dosya: {drops or "(yok — aday listesini genişlet: --limit/--files)"}')
        if not drops:
            print('  Tek dosya hiçbir şeyi taşımıyor: ya iki dosya birlikte, ya kırılma bizim değil.')
        return bool(drops)
    finally:
        if keep:
            print(f'  worktree bırakıldı: {lab}')
        else:
            run('worktree', 'remove', '--force', str(lab))
            shutil.rmtree(parent, ignore_errors=True)
        after = run('status', '--porcelain').stdout
        print(f'  çalışma ağacı {"değişmedi ✓" if after == before else "DEĞİŞTİ — elle bak ✗"}')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--theirs', default='upstream/main', help='upstream ref (default upstream/main)')
    parser.add_argument('--only', choices=('preflight', 'merge', 'coverage', 'worktree'), action='append')
    parser.add_argument('--test', help='worktree adımı: tek bir kırmızı test (pytest adresi)')
    parser.add_argument('--files', help='worktree adımı: yalnız bu dosyaları sına (virgülle ayrılmış)')
    parser.add_argument('--limit', type=int, default=12, help='worktree adımı: en çok kaç aday sınansın')
    parser.add_argument('--keep-worktree', action='store_true', help='iş bitince lab worktree bırakılsın')
    args = parser.parse_args()
    steps = args.only or ['preflight', 'merge', 'coverage']
    ok = True
    if 'preflight' in steps:
        ok &= preflight()
    if 'merge' in steps:
        ok &= report_merge(args.theirs)
    if 'coverage' in steps:
        coverage()
    if 'worktree' in steps:
        files = [f.strip() for f in args.files.split(',')] if args.files else None
        ok &= worktree(args.theirs, args.test, files, args.limit, args.keep_worktree)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())