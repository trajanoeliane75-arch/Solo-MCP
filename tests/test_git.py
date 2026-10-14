"""Local Git integration tests: real checkout, never network."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import solo_git as local_git


@unittest.skipUnless(shutil.which("git"), "Git não instalado")
class LocalGitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "checkout"
        self.root.mkdir()
        self.call("init", "-q")
        (self.root / "README.md").write_text("inicial\n", encoding="utf-8")
        self.call("add", "README.md")
        self.call("-c", "user.name=Solo Tests", "-c", "user.email=tests@example.invalid",
                  "commit", "-qm", "First commit")

    def call(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args],
                              capture_output=True, text=True, check=True)

    def test_recognizes_checkout_and_branch(self):
        info = local_git.inspect_local_git(self.root)
        self.assertTrue(info["is_repo"])
        self.assertEqual(info["root"], str(self.root))
        self.assertTrue(info["branch"])
        self.assertEqual(info["changed"], 0)
        self.assertEqual(info["untracked"], 0)
        self.assertIsNone(info["github_url"])

    def test_detects_modified_and_untracked(self):
        (self.root / "README.md").write_text("modificado\n", encoding="utf-8")
        (self.root / "new.py").write_text("print(1)\n", encoding="utf-8")
        info = local_git.inspect_local_git(self.root)
        self.assertEqual(info["changed"], 1)
        self.assertEqual(info["untracked"], 1)

    def test_ssh_github_remote_opens_canonical_url(self):
        self.call("remote", "add", "origin", "git@github.com:my-team/hello-world.git")
        info = local_git.inspect_local_git(self.root)
        self.assertEqual(info["remote_name"], "origin")
        self.assertEqual(info["github_name"], "my-team/hello-world")
        self.assertEqual(info["github_url"], "https://github.com/my-team/hello-world")

    def test_secret_in_remote_url_is_redacted(self):
        self.call("remote", "add", "origin",
                  "https://alice:ghp_FAKE_SECRET@github.com/org/secret-repo.git")
        info = local_git.inspect_local_git(self.root)
        self.assertEqual(info["github_url"], "https://github.com/org/secret-repo")
        self.assertNotIn("ghp_FAKE_SECRET", str(info))
        self.assertNotIn("alice", str(info))

    def test_non_github_remote_is_not_clickable(self):
        self.call("remote", "add", "origin", "https://example.com/private/repo.git")
        info = local_git.inspect_local_git(self.root)
        self.assertEqual(info["remote_name"], "origin")
        self.assertIsNone(info["github_url"])
        self.assertIsNone(info["github_name"])

    def test_not_a_repo_reports_instead_of_crashing(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        info = local_git.inspect_local_git(outside)
        self.assertFalse(info["is_repo"])
        self.assertIn("não é um repositório", info["message"])

    def test_never_uses_network_or_mutating_commands(self):
        with patch.object(local_git.subprocess, "run", wraps=subprocess.run) as call:
            local_git.inspect_local_git(self.root)
        args = [x.args[0] for x in call.call_args_list]
        self.assertTrue(args)
        self.assertTrue(all(argv[0] == "git" for argv in args))
        self.assertTrue(all(argv[-1] != "push" for argv in args))
        self.assertTrue(all("pull" not in argv for argv in args))
        self.assertTrue(all("fetch" not in argv for argv in args))
        self.assertTrue(all(x.kwargs.get("timeout") == 12 for x in call.call_args_list))


class GitURLTests(unittest.TestCase):
    def test_https_remote(self):
        self.assertEqual(local_git.github_remote("https://github.com/a/b.git"),
                         {"full_name": "a/b", "url": "https://github.com/a/b"})

    def test_ssh_remote(self):
        self.assertEqual(local_git.github_remote("ssh://git@github.com/a/b.git"),
                         {"full_name": "a/b", "url": "https://github.com/a/b"})

    def test_reject_hosts_and_untrusted_urls(self):
        for raw in (
            "https://github.com.evil.com/a/b",
            "https://evil.example/github.com/a/b",
            "https://github.com/a/b?token=secret",
            "https://github.com/a/b#fragment",
            "file:///etc/passwd",
            "https://github.com/a/b/x",
            "https://github.com:bad/a/b",
            "git@notgithub.com:a/b",
            "http://github.com/a/b",
            "https://github.com/a/../../b",
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(local_git.github_remote(raw))

    def test_no_remote_token_exposed(self):
        info = local_git.github_remote(
            "https://user:secret-123@github.com/org/my-repo.git"
        )
        self.assertEqual(info["url"], "https://github.com/org/my-repo")
        self.assertNotIn("secret-123", str(info))


if __name__ == "__main__":
    unittest.main()
