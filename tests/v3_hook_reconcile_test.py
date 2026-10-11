#!/usr/bin/env python3
"""Offline tests for explicit hook reconciliation (#205)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from v3_package_helpers import clean_environ, isolated_path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "template/.claude/scripts"
INSTALLER = ROOT / "scripts/install_v3.py"
CLI = ROOT / "scripts/beyin_v3.py"
ENTRY = ROOT / "scripts/beyin_entry.py"


def decoded_command(command):
    import base64
    import re
    match = re.search(r"-EncodedCommand\s+([A-Za-z0-9+/=]+)", command, re.IGNORECASE)
    return base64.b64decode(match.group(1)).decode("utf-16le") if match else command


class HookReconcileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="v3-hook-reconcile-test-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.vault = self.root / "Synthetic Beyin Space"
        self.vault.mkdir()
        self.state = self.root / "state outside vault"
        home = self.root / "isolated-home"
        home.mkdir()
        self.env = {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "APPDATA": str(home / "appdata"),
            "LOCALAPPDATA": str(home / "localappdata"),
            "TEMP": str(self.root),
            "TMP": str(self.root),
            "PATH": isolated_path(),
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "BEYIN_V3_NO_SPAWN": "1",
        }
        for key in ("SYSTEMROOT", "WINDIR"):
            if key in os.environ:
                self.env[key] = os.environ[key]
        environment = clean_environ()
        environment.start()
        self.addCleanup(environment.stop)
        sys.path.insert(0, str(SCRIPTS))
        self.addCleanup(lambda: sys.path.remove(str(SCRIPTS)))

    def install(self):
        result = subprocess.run(
            [sys.executable, str(INSTALLER), "--vault", str(self.vault), "--state", str(self.state)],
            capture_output=True, text=True, encoding="utf-8", cwd=self.vault, env=self.env, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def doctor_report(self):
        doctor = subprocess.run(
            [sys.executable, str(CLI), "--vault", str(self.vault), "--state", str(self.state), "doctor"],
            capture_output=True, text=True, encoding="utf-8", cwd=self.vault, env=self.env, timeout=30,
        )
        self.assertEqual(doctor.returncode, 0, doctor.stderr)
        return json.loads(doctor.stdout)

    def stale_hook_commands(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("v3_hook_installer", INSTALLER)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        old = self.root / "other account" / "Old Vault"
        return installer.commands([
            str(self.root / "other account" / "python.exe"),
            str(old / ".claude/scripts/beyin_v3_hook.py"),
            "--vault", str(old),
            "--state", str(self.root / "other account" / "state"),
            "--harness", "claude",
        ])

    def test_hook_reconcile_noop_when_valid(self):
        self.install()
        # Hooks are valid initially; reconcile should do nothing
        import importlib.util
        spec = importlib.util.spec_from_file_location("v3_cli", CLI)
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        result = cli.hook_reconcile(self.vault, self.state)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["reconciled_count"], 0)
        self.assertEqual(result["files"], [])

    def test_hook_reconcile_fixes_stale_hooks_and_creates_backup(self):
        self.install()
        stale_posix, stale_win = self.stale_hook_commands()
        stale_cmd = stale_win if os.name == "nt" else stale_posix

        claude_settings = self.vault / ".claude/settings.local.json"
        data = json.loads(claude_settings.read_text(encoding="utf-8"))
        user_hook = {"type": "command", "command": "echo user-owned-custom-hook"}
        data["hooks"]["SessionStart"] = [
            {"hooks": [{"type": "command", "command": stale_cmd, "timeout": 20}]},
            {"hooks": [user_hook]},
        ]
        claude_settings.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # Doctor must report stale
        report = self.doctor_report()
        self.assertEqual(report["status"], "needs_attention")
        self.assertEqual(report["hook_paths"]["status"], "stale")

        # Run hook-reconcile
        result = subprocess.run(
            [sys.executable, str(CLI), "--vault", str(self.vault), "--state", str(self.state), "hook-reconcile"],
            capture_output=True, text=True, encoding="utf-8", cwd=self.vault, env=self.env, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        recon_data = json.loads(result.stdout)
        self.assertEqual(recon_data["status"], "reconciled")
        self.assertGreaterEqual(recon_data["reconciled_count"], 1)

        # Verify backup exists and contains stale command
        backup_file = self.vault / ".claude/settings.local.json.bak"
        self.assertTrue(backup_file.is_file(), "Backup file must be created")
        backup_data = json.loads(backup_file.read_text(encoding="utf-8"))
        backup_commands = [h["command"] for g in backup_data["hooks"]["SessionStart"] for h in g["hooks"]]
        self.assertIn(stale_cmd, backup_commands)

        # Verify updated settings file
        new_data = json.loads(claude_settings.read_text(encoding="utf-8"))
        new_commands = [h["command"] for g in new_data["hooks"]["SessionStart"] for h in g["hooks"]]
        self.assertNotIn(stale_cmd, new_commands)
        # User hook is completely preserved
        self.assertIn(user_hook["command"], new_commands)

        # Doctor now reports ok
        report_after = self.doctor_report()
        self.assertEqual(report_after["hook_paths"]["status"], "ok")

    def test_hook_reconcile_human_output_and_doctor_hint(self):
        self.install()
        stale_posix, stale_win = self.stale_hook_commands()
        stale_cmd = stale_win if os.name == "nt" else stale_posix

        claude_settings = self.vault / ".claude/settings.local.json"
        data = json.loads(claude_settings.read_text(encoding="utf-8"))
        data["hooks"]["SessionStart"] = [
            {"hooks": [{"type": "command", "command": stale_cmd, "timeout": 20}]}
        ]
        claude_settings.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # Doctor human output contains reconciliation hint
        doc_res = subprocess.run(
            [sys.executable, str(self.vault / "beyin.py"), "doctor", "--human"],
            capture_output=True, text=True, encoding="utf-8", cwd=self.vault, env=self.env, timeout=30,
        )
        doc_output = doc_res.stdout + doc_res.stderr
        self.assertIn("hook-reconcile", doc_output)

        # Run beyin.py hook-reconcile --human
        rec_res = subprocess.run(
            [sys.executable, str(self.vault / "beyin.py"), "hook-reconcile", "--human"],
            capture_output=True, text=True, encoding="utf-8", cwd=self.vault, env=self.env, timeout=30,
        )
        rec_output = rec_res.stdout + rec_res.stderr
        self.assertEqual(rec_res.returncode, 0, rec_res.stderr)
        self.assertIn("Hook mutabakati tamamlandi", rec_output)
        self.assertIn(".claude/settings.local.json", rec_output)
        self.assertIn(".bak", rec_output)

    def test_hook_reconcile_installer_flag(self):
        self.install()
        stale_posix, stale_win = self.stale_hook_commands()
        stale_cmd = stale_win if os.name == "nt" else stale_posix

        claude_settings = self.vault / ".claude/settings.local.json"
        data = json.loads(claude_settings.read_text(encoding="utf-8"))
        data["hooks"]["SessionStart"] = [
            {"hooks": [{"type": "command", "command": stale_cmd, "timeout": 20}]}
        ]
        claude_settings.write_text(json.dumps(data, indent=2), encoding="utf-8")

        # Run install_v3.py --reconcile-hooks
        result = subprocess.run(
            [sys.executable, str(INSTALLER), "--vault", str(self.vault), "--state", str(self.state), "--reconcile-hooks"],
            capture_output=True, text=True, encoding="utf-8", cwd=self.vault, env=self.env, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        recon_data = json.loads(result.stdout)
        self.assertEqual(recon_data["status"], "reconciled")
        self.assertTrue((self.vault / ".claude/settings.local.json.bak").is_file())


if __name__ == "__main__":
    unittest.main()
