import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import solo_mcp as sm
import solo_projects as projects
import solo_workspaces as ws


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "experiment"
        self.project.mkdir()
        (self.project / "hello.txt").write_text("Olá workspace", encoding="utf-8")
        self.config = {"control_repo": "owner/private", "projects": {}}
        projects.register_project(self.config, "dev", self.project, "first/legacy")
        self.context_patch = patch.object(ws, "CONTEXT_ROOT", self.root / "private" / "workspaces")
        self.context_patch.start()
        self.addCleanup(self.context_patch.stop)

    def test_legacy_project_remains_named_workspace(self):
        task = {"version": 1, "project": "dev", "action": "read", "path": "hello.txt"}
        self.assertEqual(sm.do_task(self.config, task)["content"], "Olá workspace")

    def test_workspace_alias_executes_on_same_root(self):
        result = sm.do_task(self.config, {"version": 1, "workspace": "dev",
                                          "action": "read", "path": "hello.txt"})
        self.assertEqual(result["content"], "Olá workspace")

    def test_conflicting_names_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "diferentes"):
            ws.choose_workspace({"project": "dev", "workspace": "other"})

    def test_implicit_active_not_allowed_for_remote_tasks(self):
        ws.select_active(self.config, "dev")
        with self.assertRaisesRegex(ValueError, "Informe um workspace"):
            sm.do_task(self.config, {"version": 1, "action": "list", "path": "."})

    def test_default_context_is_private(self):
        path = ws.init_context(self.config, "dev")
        self.assertTrue(path.exists())
        self.assertIn("Objetivo", path.read_text(encoding="utf-8"))
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertFalse(self.config["projects"]["dev"].get("share_context", False))

    def test_context_not_silently_shared(self):
        ws.init_context(self.config, "dev")
        with self.assertRaises(PermissionError):
            sm.do_task(self.config, {"version": 1, "workspace": "dev",
                                     "action": "workspace_context"})
        info = sm.do_task(self.config, {"version": 1, "workspace": "dev",
                                        "action": "workspace_info"})
        self.assertFalse(info["context_shared"])
        self.assertTrue(info["context_available"])

    def test_explicit_remote_context_sharing(self):
        ws.init_context(self.config, "dev")
        ws.set_context_sharing(self.config, "dev", True)
        result = sm.do_task(self.config, {"version": 1, "workspace": "dev",
                                          "action": "workspace_context"})
        self.assertIn("Workspace: dev", result["content"])
        self.assertEqual(result["workspace"], "dev")
        self.assertEqual(result["bytes"], len(result["content"].encode("utf-8")))

    def test_context_requires_read_permission_even_when_shared(self):
        ws.init_context(self.config, "dev")
        ws.set_context_sharing(self.config, "dev", True)
        projects.set_permissions(self.config, "dev", "write")
        with self.assertRaises(PermissionError):
            sm.do_task(self.config, {"version": 1, "workspace": "dev",
                                     "action": "workspace_context"})

    def test_context_read_is_not_empty_when_shared(self):
        ws.init_context(self.config, "dev")
        ws.set_context_sharing(self.config, "dev", True)
        self.assertTrue(ws.read_context(self.config, "dev", remote=True).startswith("# Workspace"))

    def test_init_never_overwrites_context(self):
        path = ws.init_context(self.config, "dev")
        path.write_text("Manual edit", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "existe"):
            ws.init_context(self.config, "dev")
        self.assertEqual(path.read_text(encoding="utf-8"), "Manual edit")

    def test_context_replace_from_local_file(self):
        ws.init_context(self.config, "dev")
        source = self.root / "notes.md"
        source.write_text("# Decisões\n\nContinuar projeto.\n", encoding="utf-8")
        target = ws.replace_context(self.config, "dev", source)
        self.assertEqual(target.read_text(encoding="utf-8"), source.read_text(encoding="utf-8"))
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_context_rejects_binary_and_oversize(self):
        source = self.root / "notes.md"
        for blob in (b"x" * (ws.MAX_CONTEXT_BYTES + 1), b"a\x00b", b"", b"\xff"):
            with self.subTest(blob=blob[:10]):
                source.write_bytes(blob)
                with self.assertRaises((ValueError, UnicodeError)):
                    ws.replace_context(self.config, "dev", source)

    def test_workspace_names_cannot_escape_context_directory(self):
        for name in ("../secret", ".ssh", "/etc/passwd", "a/b", ""):
            with self.subTest(name=name), self.assertRaises(ValueError):
                ws.context_path(name)

    def test_context_symlink_is_rejected(self):
        ws.init_context(self.config, "dev")
        location = ws.context_path("dev")
        location.unlink()
        location.symlink_to(self.root / "notes.txt")
        with self.assertRaises(ValueError):
            ws.read_context(self.config, "dev")
        source = self.root / "new.md"
        source.write_text("new", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Symlink"):
            ws.replace_context(self.config, "dev", source)

    def test_legacy_repo_link_is_visible(self):
        repos = ws.repository_links(self.config, "dev")
        self.assertEqual(repos, [{"provider": "github",
                                   "full_name": "first/legacy", "account": ""}])

    def test_links_multiple_repos_from_different_accounts(self):
        ws.link_repository(self.config, "dev", "other/team", "corporate")
        ws.link_repository(self.config, "dev", "my/experiments", "personal")
        repos = ws.repository_links(self.config, "dev")
        self.assertEqual(len(repos), 3)
        self.assertEqual(repos[1]["account"], "corporate")
        self.assertEqual(repos[2]["account"], "personal")
        # Those aliases are metadata. They do not grant connector permissions.
        with self.assertRaisesRegex(ValueError, "já está associado"):
            ws.link_repository(self.config, "dev", "other/team", "corporate")

    def test_unlink_removes_metadata_not_repositories(self):
        ws.link_repository(self.config, "dev", "second/repo", "work")
        ws.unlink_repository(self.config, "dev", "second/repo", "work")
        ws.unlink_repository(self.config, "dev", "first/legacy")
        self.assertEqual(ws.repository_links(self.config, "dev"), [])
        self.assertTrue((self.project / "hello.txt").exists())

    def test_invalid_alias_and_repo_rejected(self):
        for repo, account in (("https://github.com/owner/x", "work"),
                              ("owner/x", "../ssh"), ("bad_name", "")):
            with self.subTest(repo=repo, account=account), self.assertRaises(ValueError):
                ws.link_repository(self.config, "dev", repo, account)

    def test_root_replacement_preserves_workspace_metadata(self):
        ws.link_repository(self.config, "dev", "second/repo", "team")
        ws.set_context_sharing(self.config, "dev", True)
        projects.set_permissions(self.config, "dev", "read,desktop")
        new_root = self.root / "new_root"
        new_root.mkdir()
        projects.register_project(self.config, "dev", new_root, replace=True)
        entry = self.config["projects"]["dev"]
        self.assertTrue(entry["share_context"])
        self.assertTrue(entry["permissions"]["desktop"])
        self.assertEqual(len(ws.repository_links(self.config, "dev")), 2)

    def test_active_selection_is_local_only(self):
        ws.select_active(self.config, "dev")
        self.assertEqual(ws.active_workspace(self.config), "dev")
        self.assertEqual(self.config["control_repo"], "owner/private")

    def test_workspace_info_contains_no_context_text(self):
        ws.init_context(self.config, "dev")
        info = ws.workspace_info(self.config, "dev")
        self.assertEqual(info["workspace"], "dev")
        self.assertIn("repositories", info)
        self.assertNotIn("content", info)

    def test_cli_workspace_status(self):
        output = io.StringIO()
        with patch.object(sm, "load_config", return_value=self.config), \
             patch.object(sys, "argv", ["solo_mcp.py", "workspace", "status", "--name", "dev"]), \
             contextlib.redirect_stdout(output):
            sm.cli()
        result = json.loads(output.getvalue())
        self.assertEqual(result["workspace"], "dev")
        self.assertFalse(result["context_shared"])

    def test_cli_workspace_use_then_status(self):
        out = io.StringIO()
        with patch.object(sm, "load_config", return_value=self.config), \
             patch.object(sm, "save_config") as save, \
             patch.object(sys, "argv", ["solo_mcp.py", "workspace", "use", "dev"]), \
             contextlib.redirect_stdout(out):
            sm.cli()
        self.assertEqual(self.config["active_workspace"], "dev")
        save.assert_called_once()
        self.assertIn("CLI local", out.getvalue())

    def test_cli_workspace_create_and_context_init(self):
        config = {"control_repo": "owner/private", "projects": {}}
        with patch.object(sm, "load_config", return_value=config), \
             patch.object(sm, "save_config") as save, \
             patch.object(sys, "argv", ["solo_mcp.py", "workspace", "create",
                                        "--name", "new", "--path", str(self.project)]), \
             contextlib.redirect_stdout(io.StringIO()):
            sm.cli()
        self.assertIn("new", config["projects"])
        self.assertTrue(ws.context_path("new").is_file())
        save.assert_called_once()

    def test_cli_workspace_context_share_opt_in(self):
        with patch.object(sm, "load_config", return_value=self.config), \
             patch.object(sm, "save_config") as save, \
             patch.object(sys, "argv", ["solo_mcp.py", "workspace", "context",
                                        "share", "--name", "dev", "--on"]), \
             contextlib.redirect_stdout(io.StringIO()):
            sm.cli()
        self.assertTrue(self.config["projects"]["dev"]["share_context"])
        save.assert_called_once()


if __name__ == "__main__":
    unittest.main()
