"""Offline product fixture helpers. Never downloads a release or reads user state."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / 'scripts/install_v3.py'
BUILDER = ROOT / 'scripts/build_v3_release.py'


def windows_runtime_env():
    """Variables Windows needs even in a cleared test environment. Without SYSTEMROOT,
    ssl.SSLContext() fails on Python 3.14 (OpenSSL 3.5): '[SSL] unknown error (0xa080024)'."""
    return {key: os.environ[key] for key in ('SYSTEMROOT', 'WINDIR') if key in os.environ}


def isolated_env(home):
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    env = {'HOME': str(home), 'USERPROFILE': str(home), 'APPDATA': str(home / 'appdata'),
           'LOCALAPPDATA': str(home / 'localappdata'), 'TEMP': str(home), 'TMP': str(home),
           'PATH': str(Path(sys.executable).parent) + os.pathsep + os.defpath,
           'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONIOENCODING': 'utf-8', 'BEYIN_V3_NO_SPAWN': '1',
           # The product dates windows in UTC; a local-time subprocess reads a different day for
           # three hours a day. Pinned here as well as in tests/conftest.py because callers build
           # their own env from this dict and would otherwise inherit the developer's timezone.
           'TZ': 'UTC'}
    env.update(windows_runtime_env())
    return env


def run_python(script, args, cwd, env, payload=None):
    return subprocess.run([sys.executable, str(script), *map(str, args)], cwd=cwd, env=env,
                          input=json.dumps(payload).encode('utf-8') if payload is not None else None,
                          capture_output=True, timeout=60)


def install(vault, state, env):
    return run_python(INSTALLER, ['--vault', vault, '--state', state], ROOT, env)


def build_package(path, version, env):
    if not BUILDER.is_file():
        raise AssertionError('Versioned release builder not implemented')
    result = run_python(BUILDER, ['--output', path, '--version', version], ROOT, env)
    if result.returncode:
        raise AssertionError('Offline package build failed: ' + result.stderr.decode('utf-8', errors='replace'))
    return Path(path)


def snapshot(root):
    root = Path(root)
    return {p.relative_to(root).as_posix(): ('symlink:' + os.readlink(p) if p.is_symlink()
            else hashlib.sha256(p.read_bytes()).hexdigest())
            for p in sorted(root.rglob('*')) if p.is_file() or p.is_symlink()}


def rewrite_zip(source, target, mutate):
    with zipfile.ZipFile(source) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    mutate(files)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return Path(target)
