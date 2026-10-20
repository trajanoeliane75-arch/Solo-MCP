"""Regression tests for Solo Context: read-only capability, freshness and privacy."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import solo_context_index as context
import solo_mcp as solo


class ContextIndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "workspace"
        self.root.mkdir()
        env = patch.dict(os.environ, {"XDG_STATE_HOME": str(self.base / "state")})
        env.start()
        self.addCleanup(env.stop)
        self.config = {"projects": {
            "demo": {"path": str(self.root), "permissions": {"read": True}}
        }}

    def write(self, filename, content):
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def query(self, q, **extra):
        return solo.do_task(self.config, {
            "version": 1, "workspace": "demo", "action": "context_search",
            "query": q, **extra
        })

    def test_returns_real_code_matches_and_line_numbers(self):
        self.write("src/ink.py", "def initialize():\n    pass\n\ndef pen_stroke():\n    return 'drawing'\n")
        self.write("src/other.py", "def open_document():\n    pass\n")
        result = self.query("pen_stroke")
        self.assertEqual(result["matches"][0]["path"], "src/ink.py")
        self.assertLessEqual(result["matches"][0]["line_start"], 4)
        self.assertGreaterEqual(result["matches"][0]["line_end"], 4)
        self.assertIn("pen_stroke", result["matches"][0]["excerpt"])
        self.assertGreaterEqual(result["files_indexed"], 2)

    def test_incremental_update_and_deletion(self):
        file = self.write("draw.py", "def oldbrush(): pass\n")
        self.assertTrue(self.query("oldbrush")["matches"])
        file.write_text("def newstroke(): pass\n", encoding="utf-8")
        self.assertFalse(self.query("oldbrush")["matches"])
        self.assertTrue(self.query("newstroke")["matches"])
        file.unlink()
        self.assertFalse(self.query("newstroke")["matches"])

    def test_separate_workspaces(self):
        self.write("code.py", "def ink_workflow(): pass")
        result = self.query("ink_workflow")
        self.assertTrue(result["matches"])
        other = self.base / "other"
        other.mkdir()
        self.config["projects"]["other"] = {"path": str(other), "permissions": {"read": True}}
        response = solo.do_task(self.config, {
            "version": 1, "workspace": "other", "action": "context_search",
            "query": "ink_workflow"
        })
        self.assertFalse(response["matches"])

    def test_ignores_hidden_build_secrets_binary_and_external_symlink(self):
        self.write(".env", "password=mytestvalue")
        self.write(".git/config.py", "def forbidden_git_marker(): pass")
        self.write("node_modules/mod.js", "function module_marker(){}")
        self.write("build-mint/generated.py", "def generated_marker(): pass")
        self.write("credentials.py", "def credential_marker(): pass")
        self.write("sample.py", "def safe_marker(): pass")
        binary = self.root / "binary.py"
        binary.write_bytes(b"abc\x00def")
        outer = self.base / "outside.py"
        outer.write_text("def external_marker(): pass")
        (self.root / "link.py").symlink_to(outer)
        self.assertTrue(self.query("safe_marker")["matches"])
        for term in ("forbidden_git_marker", "module_marker", "generated_marker",
                     "credential_marker", "external_marker"):
            self.assertFalse(self.query(term)["matches"], term)
        self.assertNotIn("binary.py", [m["path"] for m in self.query("abc")["matches"]])

    def test_requires_read_permission_and_does_not_create_index(self):
        self.config["projects"]["demo"]["permissions"] = {"write": True}
        with self.assertRaises(PermissionError):
            self.query("sample")
        self.assertFalse((self.base / "state").exists())

    def test_private_index_permissions(self):
        self.write("sample.py", "def unique_identifier(): pass")
        self.query("unique_identifier")
        path = context._index_path("demo", self.root)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_search_query_sanitized_and_bounded(self):
        self.write("foo.py", "def pressure_event(): pass")
        self.assertTrue(self.query("pressure_event OR DROP TABLE")["matches"])
        for bad in ("", "!", "x" * 201, None):
            with self.assertRaises(ValueError):
                self.query(bad)
        for bad_limit in (0, 100, "3", True):
            with self.assertRaises(ValueError):
                self.query("pressure_event", limit=bad_limit)

    def test_oversize_not_indexed(self):
        self.write("large.py", "oversizecode " * 9000)
        self.assertFalse(self.query("oversizecode")["matches"])

    def test_no_automatic_context_sharing_required(self):
        # Searching code requires normal read access, but never exposes the
        # private CONTEXT.md unless workspace context sharing is enabled.
        self.write("src/main.py", "def cursor_smoothing(): pass")
        result = self.query("cursor_smoothing")
        self.assertEqual(result["matches"][0]["path"], "src/main.py")
        self.assertNotIn("content", result)


if __name__ == "__main__":
    unittest.main()
