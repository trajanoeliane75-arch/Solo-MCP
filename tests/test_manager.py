"""Tests for local GUI backend; one optional actual Tk smoke test under Xvfb."""
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import solo_mcp as sm
import solo_desktop as desktop
import solo_manager as manager
import solo_projects as projects
import solo_workspaces as workspaces


class ManagerBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "project"
        self.project.mkdir()
        (self.project / "original.txt").write_text("not deleted", encoding="utf-8")
        self.saved = {"control_repo": "owner/private", "projects": {}}
        projects.register_project(self.saved, "test", self.project, "owner/legacy")
        self.root_patch = patch.object(workspaces, "CONTEXT_ROOT", self.base / "context")
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.load_patch = patch.object(sm, "load_config", side_effect=lambda: copy.deepcopy(self.saved))
        self.load_patch.start()
        self.addCleanup(self.load_patch.stop)
        self.save_patch = patch.object(sm, "save_config", side_effect=self._save)
        self.saver = self.save_patch.start()
        self.addCleanup(self.save_patch.stop)
        self.backend = manager.ManagerBackend()

    def _save(self, config):
        self.saved = copy.deepcopy(config)

    def test_lists_existing_workspace_without_changing_control_repo(self):
        names, selected = self.backend.names()
        self.assertEqual(names, ["test"])
        self.assertIsNone(selected)
        self.assertEqual(self.saved["control_repo"], "owner/private")

    def test_new_workspace_default_read_only(self):
        other = self.base / "new-workspace"
        other.mkdir()
        created = self.backend.create("new", str(other))
        self.assertEqual(created["workspace"], "new")
        self.assertEqual(created["permissions"]["read"], True)
        self.assertEqual(created["permissions"]["terminal"], False)
        self.assertEqual(self.saved["projects"]["new"]["path"], str(other))

    def test_new_workspace_rejects_duplicate(self):
        with self.assertRaises(ValueError):
            self.backend.create("test", self.project)
        self.assertEqual(len(self.saved["projects"]), 1)

    def test_active_workspace_only_affects_local_preference(self):
        self.backend.select("test")
        self.assertEqual(self.backend.names(), (["test"], "test"))
        self.assertEqual(self.saved["control_repo"], "owner/private")

    def test_permission_checkboxes_replace_exact_allowed_set(self):
        result = self.backend.permissions("test", {"read", "desktop"})
        self.assertTrue(result["read"])
        self.assertTrue(result["desktop"])
        for name in ("write", "environment", "terminal"):
            self.assertFalse(result[name])
        self.assertEqual(self.saved["projects"]["test"]["permissions"], result)

    def test_setting_permissions_cannot_change_unknown_capabilities(self):
        with self.assertRaises(ValueError):
            self.backend.permissions("test", {"sudo"})
        self.assertEqual(self.saved["projects"]["test"]["permissions"]["terminal"], False)

    def test_links_multiple_github_accounts_as_metadata(self):
        linked = self.backend.link_repository("test", "university/research", "university")
        self.assertEqual(linked["account"], "university")
        self.backend.link_repository("test", "personal/forks", "personal")
        info = self.backend.details("test")
        self.assertEqual([x["full_name"] for x in info["repositories"]],
                         ["owner/legacy", "university/research", "personal/forks"])
        self.assertEqual(self.saved["control_repo"], "owner/private")

    def test_unlink_does_not_delete_project_folder(self):
        self.backend.unlink_repository("test", "owner/legacy")
        self.assertFalse(self.backend.details("test")["repositories"])
        self.assertTrue((self.project / "original.txt").is_file())

    def test_private_context_can_be_edited_in_app(self):
        text = "# Projeto\n\nArquitetura revisada.\n"
        target = self.backend.save_context("test", text)
        self.assertEqual(self.backend.read_context("test"), text)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.backend.details("test")["context_shared"])

    def test_context_is_not_shared_before_opt_in(self):
        self.backend.save_context("test", "# Projeto\n")
        with self.assertRaises(PermissionError):
            workspaces.read_context(self.backend.load(), "test", remote=True)

    def test_context_sharing_requires_existing_file(self):
        with self.assertRaises(ValueError):
            self.backend.share_context("test", True)
        self.assertFalse(self.backend.details("test")["context_shared"])

    def test_explicit_share_then_disable(self):
        self.backend.save_context("test", "# Contexto aprovado\n")
        self.assertTrue(self.backend.share_context("test", True))
        self.assertEqual(self.backend.details("test")["context_shared"], True)
        self.assertIn("Contexto aprovado", workspaces.read_context(self.backend.load(), "test", remote=True))
        self.assertFalse(self.backend.share_context("test", False))
        with self.assertRaises(PermissionError):
            workspaces.read_context(self.backend.load(), "test", remote=True)

    def test_context_text_rejects_binary_and_oversize(self):
        for txt in ("abc\x00pass", "x" * (workspaces.MAX_CONTEXT_BYTES + 1), ""):
            with self.subTest(text=txt[:8]), self.assertRaises(ValueError):
                self.backend.save_context("test", txt)

    def test_remove_only_unregisters_not_delete_files(self):
        self.backend.select("test")
        self.assertEqual(self.backend.remove("test"), "test")
        self.assertEqual(self.saved["projects"], {})
        self.assertNotIn("active_workspace", self.saved)
        self.assertEqual((self.project / "original.txt").read_text(encoding="utf-8"), "not deleted")

    def test_environment_checks_are_read_only(self):
        responses = [
            subprocess.CompletedProcess([], 0, "active\n", ""),
            subprocess.CompletedProcess([], 0, "true\n", ""),
            subprocess.CompletedProcess([], 0, "", ""),
        ]
        with patch.object(manager.subprocess, "run", side_effect=responses) as run:
            result = self.backend.system_checks()
        self.assertIn("Serviço Solo-MCP: ativo", result)
        self.assertIn("Podman: instalado e funcionando sem root", result)
        self.assertIn("Imagem Python 3.12: pronta", result)
        self.assertEqual(run.call_count, 3)
        self.assertFalse(any("install" in call.args[0] for call in run.call_args_list))
        self.assertFalse(any("pull" in call.args[0] for call in run.call_args_list))

    def test_missing_podman_has_clear_explanation(self):
        def fake_run(argv, **_kwargs):
            if argv[0] == "podman":
                raise FileNotFoundError("podman")
            return subprocess.CompletedProcess(argv, 0, "active\n", "")
        with patch.object(manager.subprocess, "run", side_effect=fake_run) as run:
            result = self.backend.system_checks()
        self.assertIn("Podman: não instalado", result)
        self.assertIn("bibliotecas do Python principal", result)
        self.assertIn("leitura dos seus workspaces continua funcionando", result)
        self.assertFalse(any("sudo" in call.args[0] for call in run.call_args_list))

    def test_manager_git_info_checks_local_selected_folder(self):
        with patch.object(manager.solo_git, "inspect_local_git",
                          return_value={"is_repo":False}) as git:
            result = self.backend.git_info("test")
        self.assertFalse(result["is_repo"])
        git.assert_called_once_with(str(self.project))


    def test_approval_panel_launches_manager_process(self):
        panel = desktop.Panel.__new__(desktop.Panel)
        panel.root = Mock()
        panel.manager_process = None
        with patch.object(desktop.subprocess, "Popen") as popen:
            panel.open_manager()
        argv = popen.call_args.args[0]
        self.assertEqual(argv[-1], "manager")
        self.assertTrue(argv[-2].endswith("solo_mcp.py"))

    @unittest.skipUnless(os.environ.get("SOLO_MCP_GUI_TESTS") == "1",
                         "Smoke test requires xvfb-run and SOLO_MCP_GUI_TESTS=1")
    def test_actual_tk_manager_renders_workspaces_and_tabs(self):
        import tkinter as tk
        from tkinter import ttk
        root = tk.Tk()
        try:
            ui = manager.ManagerWindow(root, tk, ttk, self.backend)
            root.update_idletasks()
            self.assertIn("test", ui.tree.get_children())
            self.assertEqual(ui.current, "test")
            self.assertEqual(len(ui.tabs.tabs()), 5)
            self.assertEqual(ui.context_text.get("1.0", "end-1c"), "")
            self.assertEqual(ui.permission_vars["read"].get(), True)
            self.assertEqual(ui.permission_vars["terminal"].get(), False)
            self.assertEqual(ui.heading.cget("text"), "test")

            # First-run onboarding is a real GUI prompt, not an automatic
            # download or an instruction to run pip manually.
            with patch.object(self.backend, "kit_status", return_value={"ready":False}), \
                 patch.object(manager.solo_kit, "deferred_setup", return_value=False), \
                 patch("tkinter.messagebox.askyesno", return_value=True), \
                 patch.object(ui, "prepare_kit") as prepare:
                ui._offer_kit_setup()
            prepare.assert_called_once_with(confirm=False)


            ui._render_git_status({
                "is_repo": True, "root": str(self.project),
                "branch": "main", "changed": 2, "untracked": 1,
                "remote_name": "origin", "github_name": "example/test",
                "github_url": "https://github.com/example/test"
            })
            self.assertTrue(ui.open_github_button.instate(["!disabled"]))
            self.assertIn("Branch: main", ui.git_text.get("1.0", "end"))
            with patch.object(manager.webbrowser, "open") as open_url:
                ui.open_github()
            open_url.assert_called_once_with("https://github.com/example/test")
            ui._render_git_status({"is_repo": False, "message": "Sem Git"})
            self.assertTrue(ui.open_github_button.instate(["disabled"]))


            # Exercise actual GUI callbacks with dialogs stubbed, not just construction.
            ui.permission_vars["desktop"].set(True)
            with patch("tkinter.messagebox.askyesno", return_value=True):
                ui.save_permissions()
            self.assertTrue(self.backend.details("test")["permissions"]["desktop"])

            ui.context_text.insert("1.0", "# Projeto\n\nDecisões.")
            ui.save_context()
            self.assertIn("Decisões.", self.backend.read_context("test"))

            ui.share_var.set(True)
            with patch("tkinter.messagebox.askyesno", return_value=True):
                ui.save_sharing()
            self.assertTrue(self.backend.details("test")["context_shared"])

            new_folder = self.base / "gui-created"
            new_folder.mkdir()
            with patch("tkinter.simpledialog.askstring", return_value="novo"), \
                 patch("tkinter.filedialog.askdirectory", return_value=str(new_folder)):
                ui.create_dialog()
            self.assertIn("novo", ui.tree.get_children())
            self.assertEqual(ui.current, "novo")
            self.assertFalse(self.backend.details("novo")["permissions"]["terminal"])
            self.assertEqual(ui.heading.cget("text"), "novo")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
