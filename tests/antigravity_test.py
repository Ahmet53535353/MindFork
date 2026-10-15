#!/usr/bin/env python3
"""Regression tests for the Antigravity adapter and shared model runner."""

from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "template" / ".claude" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import flush  # noqa: E402
import antigravity_hooks as hooks  # noqa: E402
import render_antigravity_hooks as renderer  # noqa: E402


def _load_compile():
    spec = importlib.util.spec_from_file_location(
        "beyin_compile_antigravity_test", SCRIPTS / "compile.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("compile module could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


COMPILE = _load_compile()


class AntigravityTest(unittest.TestCase):
    def test_transcript_extracts_only_user_and_planner_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            transcript = Path(temporary) / "transcript.jsonl"
            records = [
                {"type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "ilk soru"},
                {"type": "PLANNER_RESPONSE", "source": "MODEL", "content": "ilk cevap"},
                {"type": "PLANNER_RESPONSE", "source": "MODEL", "toolCall": {"name": "x"}},
                {"type": "TOOL_RESULT", "content": "gizli araç çıktısı"},
                {"type": "USER_INPUT", "source": "USER_EXPLICIT", "content": "son soru"},
                {"type": "PLANNER_RESPONSE", "source": "MODEL", "content": "son cevap"},
            ]
            transcript.write_text(
                "".join(json.dumps(item) + "\n" for item in records),
                encoding="utf-8",
            )
            turns = flush.read_transcript(transcript)
        self.assertEqual(
            turns,
            [
                ("user", "ilk soru"),
                ("assistant", "ilk cevap"),
                ("user", "son soru"),
                ("assistant", "son cevap"),
            ],
        )
        self.assertEqual(hooks._latest_exchange(turns), turns[-2:])

    def test_renderer_is_absolute_idempotent_and_preserves_unrelated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault with spaces"
            scripts = vault / ".claude" / "scripts"
            scripts.mkdir(parents=True)
            resolved_vault = vault.resolve()
            (scripts / "antigravity_hooks.py").write_text("# adapter\n", encoding="utf-8")
            agents = vault / ".agents"
            agents.mkdir()
            existing = {"user-hook": {"Stop": [{"command": "keep-me"}]}}
            (agents / "hooks.json").write_text(json.dumps(existing), encoding="utf-8")

            first = renderer.write(vault, "posix", Path(sys.executable))
            first_body = first.read_text(encoding="utf-8")
            second = renderer.write(vault, "posix", Path(sys.executable))
            second_body = second.read_text(encoding="utf-8")
            payload = json.loads(second.read_text(encoding="utf-8"))

        self.assertEqual(first_body, second_body)
        self.assertEqual(payload["user-hook"], existing["user-hook"])
        managed = payload["avenox-beyin"]
        self.assertEqual(set(managed), {"PreInvocation", "Stop"})
        for event, action in (("PreInvocation", "pre-invocation"), ("Stop", "stop")):
            command = managed[event][0]["command"]
            self.assertIn(str(resolved_vault), command)
            self.assertIn(action, command)

    def test_pre_invocation_uses_zero_based_first_call_and_ephemeral_message(self) -> None:
        calls = []

        def fake_runner(command, **kwargs):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {"hookSpecificOutput": {"additionalContext": "kalıcı bağlam"}}
                ),
                stderr="",
            )

        with tempfile.TemporaryDirectory() as temporary:
            with (
                mock.patch.dict(os.environ, {}, clear=True),
                mock.patch.object(hooks, "STATE_DIR", Path(temporary)),
            ):
                output = hooks.pre_invocation(
                    {"invocationNum": 0, "conversationId": "conversation-1"},
                    runner=fake_runner,
                )
                duplicate = hooks.pre_invocation(
                    {"invocationNum": 0, "conversationId": "conversation-1"},
                    runner=fake_runner,
                )
                later = hooks.pre_invocation(
                    {"invocationNum": 1, "conversationId": "conversation-1"},
                    runner=fake_runner,
                )

        self.assertEqual(output, {"injectSteps": [{"ephemeralMessage": "kalıcı bağlam"}]})
        self.assertEqual(duplicate, {})
        self.assertEqual(later, {})
        self.assertEqual(len(calls), 1)
        translated = json.loads(calls[0][1]["input"])
        self.assertEqual(translated["session_id"], "conversation-1")
        self.assertEqual(calls[0][1]["env"]["BEYIN_MODEL_RUNNER"], "antigravity")

    def test_stop_contract_only_spawns_after_fully_idle(self) -> None:
        with (
            mock.patch.dict(os.environ, {}, clear=True),
            mock.patch.object(hooks, "_spawn_worker") as spawn,
        ):
            self.assertEqual(hooks.stop({"fullyIdle": False}), {"decision": "stop"})
            self.assertEqual(hooks.stop({"fullyIdle": True}), {"decision": "stop"})
        spawn.assert_called_once_with({"fullyIdle": True})

    def test_worker_records_digest_only_after_success_and_deduplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = root / "state"
            vault = root / "vault"
            scripts = vault / ".claude" / "scripts"
            scripts.mkdir(parents=True)
            transcript = root / "transcript.jsonl"
            transcript.write_text(
                json.dumps({"type": "USER_INPUT", "content": "karar"})
                + "\n"
                + json.dumps({"type": "PLANNER_RESPONSE", "content": "uygulandı"})
                + "\n",
                encoding="utf-8",
            )
            calls = []

            def fake_run(command, **_kwargs):
                calls.append(command)
                hook_path = Path(command[command.index("--hook-input") + 1])
                session_id = json.loads(hook_path.read_text(encoding="utf-8"))["session_id"]
                flush_state = hooks._flush_state_path(session_id)
                flush_state.write_text('{"status":"ok"}\n', encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            payload = {"conversationId": "c1", "transcriptPath": str(transcript)}
            with (
                mock.patch.object(hooks, "STATE_DIR", state),
                mock.patch.object(hooks, "VAULT_ROOT", vault),
                mock.patch.object(hooks, "SCRIPT_DIR", scripts),
                mock.patch.object(hooks.subprocess, "run", side_effect=fake_run),
            ):
                hooks._run_worker(payload)
                hooks._run_worker(payload)
                state_path = hooks._conversation_state_path("c1")

            self.assertEqual(len(calls), 1)
            saved = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertRegex(saved["last_turn_digest"], r"^[0-9a-f]{64}$")

    def test_antigravity_runners_use_supported_headless_flags(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout="özet\n", stderr="")
        with tempfile.TemporaryDirectory() as temporary:
            vault = Path(temporary) / "vault"
            vault.mkdir()
            with (
                mock.patch.object(flush.shutil, "which", return_value="/usr/bin/agy"),
                mock.patch.object(flush.subprocess, "run", return_value=completed) as run,
            ):
                output, error = flush._run_antigravity("özetle", vault)
            self.assertEqual((output, error), ("özet", None))
            args = run.call_args.args[0]
            self.assertIn("-p", args)
            self.assertIn("--print-timeout", args)
            self.assertIn("--sandbox", args)
            self.assertNotIn("--effort", args)

            stage = Path(temporary) / "stage"
            stage.mkdir()
            (stage / ".beyin-compile-prompt.md").write_text("prompt", encoding="utf-8")
            with (
                mock.patch.object(COMPILE.shutil, "which", return_value="/usr/bin/agy"),
                mock.patch.object(COMPILE.subprocess, "run", return_value=completed) as run,
            ):
                self.assertIsNone(COMPILE._run_antigravity("ignored", stage))
            args = run.call_args.args[0]
            self.assertNotIn("--dangerously-skip-permissions", args)
            self.assertIn("--sandbox", args)

    def test_read_payload_handles_utf8_bom(self) -> None:
        stream = io.StringIO("\ufeff" + json.dumps({"action": "pre-invocation", "conversationId": "c1"}))
        payload = hooks._read_payload(stream)
        self.assertEqual(payload, {"action": "pre-invocation", "conversationId": "c1"})

        bytes_stream = io.BytesIO(b"\xef\xbb\xbf" + json.dumps({"action": "stop"}).encode("utf-8"))
        payload2 = hooks._read_payload(bytes_stream)
        self.assertEqual(payload2, {"action": "stop"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
