#!/usr/bin/env python3
"""Translate Antigravity hook events to the canonical Avenox Beyin engine."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any, Callable, Sequence

sys.dont_write_bytecode = True
import _portalock
import flush


SCRIPT_DIR = Path(__file__).resolve().parent
VAULT_ROOT = SCRIPT_DIR.parent.parent
STATE_DIR = SCRIPT_DIR / ".state"


def _read_payload(stream: Any = sys.stdin) -> dict[str, Any]:
    if hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(encoding="utf-8-sig", errors="replace")
        except Exception:
            pass
    raw = stream.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8-sig", errors="replace")
    if isinstance(raw, str):
        payload = json.loads(raw.lstrip("\ufeff").strip() or "{}")
    else:
        payload = json.load(stream)
    if not isinstance(payload, dict):
        raise ValueError("hook-input-not-object")
    return payload


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.chmod(temporary, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _session_start_command() -> list[str]:
    if os.name == "nt":
        return [
            "pwsh.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(VAULT_ROOT / ".claude" / "hooks" / "session-start.ps1"),
        ]
    return [str(VAULT_ROOT / ".claude" / "hooks" / "session-start.sh")]


def _start_state_path(conversation_id: str) -> Path:
    key = hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()
    return STATE_DIR / f"antigravity-start-{key}.json"


def _sweep_stale_states(now: float | None = None) -> None:
    cutoff = (now if now is not None else time.time()) - (7 * 24 * 60 * 60)
    for pattern in ("antigravity-start-*.json", "antigravity-*.json"):
        for candidate in STATE_DIR.glob(pattern):
            try:
                if not candidate.is_symlink() and candidate.stat().st_mtime < cutoff:
                    candidate.unlink()
            except (FileNotFoundError, OSError):
                pass


def pre_invocation(
    payload: dict[str, Any],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    if os.environ.get("BEYIN_INVOKED_BY"):
        return {}
    if payload.get("invocationNum") != 0:
        return {}
    conversation_id = payload.get("conversationId")
    if not isinstance(conversation_id, str) or not conversation_id:
        return {}

    state_path = _start_state_path(conversation_id)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _sweep_stale_states()
    lock_path = state_path.with_suffix(".lock")
    with lock_path.open("a+b") as lock_file:
        with _portalock.exclusive(lock_file):
            if state_path.is_file():
                return {}

            translated = {
                "session_id": conversation_id,
                "cwd": str(VAULT_ROOT),
                "hook_event_name": "SessionStart",
                "source": "startup",
            }
            environment = os.environ.copy()
            environment["CLAUDE_PROJECT_DIR"] = str(VAULT_ROOT)
            environment["BEYIN_MODEL_RUNNER"] = "antigravity"
            try:
                result = runner(
                    _session_start_command(),
                    input=json.dumps(translated, ensure_ascii=False),
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    capture_output=True,
                    cwd=VAULT_ROOT,
                    env=environment,
                    timeout=12,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return {}
            if result.returncode != 0:
                return {}
            try:
                emitted = json.loads(result.stdout)
                context = emitted["hookSpecificOutput"]["additionalContext"]
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                return {}
            if not isinstance(context, str) or not context:
                return {}
            _atomic_write_json(state_path, {"ts": int(time.time())})
            return {"injectSteps": [{"ephemeralMessage": context}]}


def _latest_exchange(turns: list[tuple[str, str]]) -> list[tuple[str, str]]:
    for index in range(len(turns) - 1, -1, -1):
        if turns[index][0] == "user":
            return turns[index:]
    return []


def _turn_digest(turns: list[tuple[str, str]]) -> str:
    encoded = json.dumps(turns, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _conversation_state_path(conversation_id: str) -> Path:
    key = hashlib.sha256(conversation_id.encode("utf-8")).hexdigest()
    return STATE_DIR / f"antigravity-{key}.json"


def _flush_state_path(session_id: str) -> Path:
    key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return STATE_DIR / f"flush-{key}.json"


def _run_worker(payload: dict[str, Any]) -> None:
    conversation_id = payload.get("conversationId")
    transcript_value = payload.get("transcriptPath")
    if not isinstance(conversation_id, str) or not conversation_id:
        return
    if not isinstance(transcript_value, str) or not transcript_value:
        return
    transcript = Path(transcript_value).expanduser()
    try:
        if transcript.is_symlink() or not transcript.is_file():
            return
        turns = _latest_exchange(flush.read_transcript(transcript))
    except (OSError, ValueError, json.JSONDecodeError):
        return
    if not turns:
        return

    digest = _turn_digest(turns)
    session_id = f"antigravity:{conversation_id}:{digest}"
    state_path = _conversation_state_path(conversation_id)
    lock_path = state_path.with_suffix(".lock")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as lock_file:
        with _portalock.exclusive(lock_file):
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
            except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
                state = {}
            if isinstance(state, dict) and state.get("last_turn_digest") == digest:
                return

            transcript_fd, transcript_name = tempfile.mkstemp(
                dir=STATE_DIR, prefix="antigravity-turn-", suffix=".jsonl"
            )
            hook_fd, hook_name = tempfile.mkstemp(
                dir=STATE_DIR, prefix="hookin-antigravity-", suffix=".json"
            )
            os.close(transcript_fd)
            os.close(hook_fd)
            turn_path = Path(transcript_name)
            hook_path = Path(hook_name)
            try:
                with turn_path.open("w", encoding="utf-8") as handle:
                    for role, content in turns:
                        handle.write(
                            json.dumps(
                                {"role": role, "content": content},
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                _atomic_write_json(
                    hook_path,
                    {
                        "session_id": session_id,
                        "transcript_path": str(turn_path),
                        "hook_event_name": "SessionEnd",
                        "source": "antigravity-stop",
                    },
                )
                environment = os.environ.copy()
                environment.pop("BEYIN_INVOKED_BY", None)
                environment["BEYIN_MODEL_RUNNER"] = "antigravity"
                subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT_DIR / "flush.py"),
                        "--hook-input",
                        str(hook_path),
                        "--reason",
                        "sessionend",
                    ],
                    cwd=VAULT_ROOT,
                    env=environment,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=270,
                    check=False,
                )
                try:
                    flush_state = json.loads(
                        _flush_state_path(session_id).read_text(encoding="utf-8")
                    )
                except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
                    flush_state = {}
                if isinstance(flush_state, dict) and flush_state.get("status") == "ok":
                    _atomic_write_json(
                        state_path,
                        {"last_turn_digest": digest, "ts": int(time.time())},
                    )
            except (OSError, subprocess.TimeoutExpired):
                pass
            finally:
                for temporary in (turn_path, hook_path):
                    try:
                        temporary.unlink()
                    except FileNotFoundError:
                        pass


def _spawn_worker(payload: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    descriptor, payload_name = tempfile.mkstemp(
        dir=STATE_DIR, prefix="antigravity-stop-", suffix=".json"
    )
    os.close(descriptor)
    payload_path = Path(payload_name)
    _atomic_write_json(payload_path, payload)
    command = [sys.executable, str(Path(__file__).resolve()), "worker", "--hook-input", str(payload_path)]
    kwargs = _portalock.detached_kwargs()
    try:
        subprocess.Popen(
            command,
            cwd=VAULT_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            **kwargs,
        )
    except OSError:
        try:
            payload_path.unlink()
        except FileNotFoundError:
            pass


def stop(payload: dict[str, Any]) -> dict[str, str]:
    if not os.environ.get("BEYIN_INVOKED_BY") and payload.get("fullyIdle") is True:
        _spawn_worker(payload)
    return {"decision": "stop"}


def _worker_from_path(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            _run_worker(payload)
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("pre-invocation", "stop", "worker"))
    parser.add_argument("--hook-input", type=Path)
    args = parser.parse_args(argv)
    if args.action == "worker":
        if args.hook_input is not None:
            return _worker_from_path(args.hook_input)
        return 0
    try:
        payload = _read_payload()
        output = pre_invocation(payload) if args.action == "pre-invocation" else stop(payload)
    except (OSError, ValueError, json.JSONDecodeError):
        output = {} if args.action == "pre-invocation" else {"decision": "stop"}
    print(json.dumps(output, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
