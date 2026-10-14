"""Tests for the app-owned Python tool kit; never download anything in unit tests."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import solo_kit as kit


class KitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "kit-v1"
        patcher = patch.object(kit, "KIT_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def fake_command(self, argv, *, timeout, env=None):
        if "-m" in argv and "venv" in argv:
            (self.root / "bin").mkdir(parents=True, exist_ok=True)
            (self.root / "bin" / "python").write_text("dummy", encoding="utf-8")
        if "playwright" in argv and "install" in argv:
            (self.root / "browsers").mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(argv, 0, "", "")

    def test_pending_kit_does_not_claim_ready(self):
        state = kit.status()
        self.assertFalse(state["ready"])
        self.assertIn("não preparado", state["browser"])

    def test_setup_uses_only_fixed_user_scoped_commands(self):
        with patch.object(kit.os, "geteuid", return_value=1000), \
             patch.object(kit, "_run", side_effect=self.fake_command) as run:
            result = kit.prepare()
        self.assertTrue(result["ready"])
        self.assertEqual(run.call_count, 4)
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][-2:], ["venv", str(self.root)])
        self.assertIn("playwright==" + kit.PLAYWRIGHT_VERSION, commands[1])
        self.assertIn("--isolated", commands[1])
        self.assertEqual(commands[2][-2:], ["install", "chromium"])
        self.assertEqual(commands[3][1:3], ["-c", commands[3][2]][:2])
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o700)
        self.assertEqual(kit.state_path().stat().st_mode & 0o777, 0o600)
        self.assertNotIn("sudo", str(commands))
        self.assertNotIn("pkexec", str(commands))
        self.assertTrue(str(self.root).startswith(self.temporary.name))

    def test_second_launch_does_not_reinstall(self):
        with patch.object(kit.os, "geteuid", return_value=1000), \
             patch.object(kit, "_run", side_effect=self.fake_command):
            kit.prepare()
        with patch.object(kit, "_run") as run:
            kit.prepare()
        run.assert_not_called()

    def test_repair_reinstalls_fixed_package_without_affecting_projects(self):
        with patch.object(kit.os, "geteuid", return_value=1000), \
             patch.object(kit, "_run", side_effect=self.fake_command) as run:
            kit.prepare()
            run.reset_mock()
            kit.prepare(repair=True)
        self.assertEqual(run.call_count, 3)
        self.assertFalse(any("workspace" in str(call.args[0]) for call in run.call_args_list))

    def test_version_change_marks_kit_not_ready(self):
        with patch.object(kit.os, "geteuid", return_value=1000), \
             patch.object(kit, "_run", side_effect=self.fake_command):
            kit.prepare()
        data=json.loads(kit.state_path().read_text(encoding="utf-8"))
        data["playwright"] = "0.0.0"
        kit.state_path().write_text(json.dumps(data), encoding="utf-8")
        self.assertFalse(kit.status()["ready"])

    def test_secrets_not_in_browser_or_pip_subprocess(self):
        with patch.dict(os.environ, {
            "SOLO_MCP_TOKEN":"top-secret",
            "PIP_INDEX_URL":"https://user:pwd@example.invalid/simple",
            "OPENAI_API_KEY":"sk-secret",
            "AWS_SECRET_ACCESS_KEY":"aws-secret",
        }):
            env=kit.browser_env()
        for secret in ("SOLO_MCP_TOKEN","PIP_INDEX_URL","OPENAI_API_KEY",
                       "AWS_SECRET_ACCESS_KEY"):
            self.assertNotIn(secret,env)
        self.assertEqual(env["PLAYWRIGHT_BROWSERS_PATH"],str(self.root/"browsers"))

    def test_setup_never_runs_as_root(self):
        with patch.object(kit.os, "geteuid", return_value=0), \
             patch.object(kit, "_run") as run:
            with self.assertRaisesRegex(RuntimeError,"sem root"):
                kit.prepare()
        run.assert_not_called()

    def test_symlink_kit_root_blocked(self):
        private=Path(self.temporary.name)/"owned"
        private.mkdir()
        self.root.symlink_to(private, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError,"link simbólico"):
            kit.private_directory()

    def test_deferring_first_run_keeps_manual_prepare_available(self):
        kit.defer_setup()
        self.assertTrue(kit.deferred_setup())
        with patch.object(kit.os,"geteuid",return_value=1000), \
             patch.object(kit,"_run",side_effect=self.fake_command):
            kit.prepare()
        self.assertFalse(kit.deferred_setup())
        self.assertTrue(kit.status()["ready"])

    def test_native_install_requires_separate_privilege_tool(self):
        with patch.object(kit,"native_missing",return_value=["import"]), \
             patch.object(kit,"system_package_plan",return_value=None), \
             patch.object(kit,"_run") as run:
            with self.assertRaisesRegex(RuntimeError,"Instalação automática"):
                kit.prepare_native()
        run.assert_not_called()

    def test_native_install_runs_only_predetermined_packages(self):
        plan=["/usr/bin/pkexec", "/usr/bin/apt-get","install","-y",
              "x11-utils","imagemagick"]
        with patch.object(kit,"native_missing",side_effect=[["import"],[]]), \
             patch.object(kit,"system_package_plan",return_value=plan), \
             patch.object(kit,"_run",return_value=None) as run:
            kit.prepare_native()
        run.assert_called_once_with(plan, timeout=420)


if __name__ == "__main__":
    unittest.main()
