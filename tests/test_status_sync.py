"""Solo status handshake: consent is visible before execution finishes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import solo_desktop as desktop
import solo_execution
import solo_mcp as sm


class FakeGithub:
    def __init__(self, task, fail_status=False):
        self.task = task
        self.fail_status = fail_status
        self.events = []
        self.comments = []
        self.closed = False

    def request(self, method, endpoint, data=None):
        self.events.append((method, endpoint, data))
        if method == "GET" and endpoint == "/repos/owner/private":
            return {"private": True, "owner": {"login": "owner"}}
        if method == "GET" and endpoint == "/repos/owner/private/issues/143":
            return {
                "state": "closed" if self.closed else "open",
                "user": {"login": "owner"},
                "body": sm.MARKER + "\n" + json.dumps(self.task)
            }
        if method == "GET" and endpoint.endswith("/issues/143/comments?per_page=100"):
            return [{"body": message} for message in self.comments]
        if method == "POST" and endpoint.endswith("/issues/143/comments"):
            message = data["body"]
            if message.startswith(desktop.STATUS_MARKER) and self.fail_status:
                raise RuntimeError("Network is temporarily unavailable")
            self.comments.append(message)
            return {}
        if method == "PATCH" and endpoint == "/repos/owner/private/issues/143":
            self.closed = True
            return {}
        raise AssertionError((method, endpoint))


class ApprovalStatusTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.journal = patch.object(
            solo_execution, "_database_path",
            return_value=self.root / "journal.sqlite3")
        self.journal.start()
        self.addCleanup(self.journal.stop)
        self.task = {
            "version": 1, "workspace": "demo", "action": "write",
            "path": "result.txt", "content": "approved",
            "expected_sha256": None,
        }
        self.config = {
            "control_repo": "owner/private",
            "projects": {"demo": {
                "path": str(self.root),
                "permissions": {"read": True, "write": True}
            }}
        }

    def test_approved_event_precedes_file_modification_and_result(self):
        gh = FakeGithub(self.task)
        observed = []
        original = sm.do_task

        def record(config, task, **kwargs):
            observed.append(tuple(gh.comments))
            return original(config, task, **kwargs)

        with patch.object(sm, "do_task", side_effect=record):
            result = desktop.decide(
                self.config, gh, 143, desktop.fingerprint(self.task), True)
        self.assertTrue(result["ok"])
        self.assertTrue((self.root / "result.txt").is_file())
        self.assertEqual((self.root / "result.txt").read_text(), "approved")
        self.assertTrue(gh.closed)
        self.assertEqual(len(gh.comments), 2)
        self.assertTrue(gh.comments[0].startswith(desktop.STATUS_MARKER))
        self.assertIn('"state":"approved"', gh.comments[0])
        self.assertTrue(gh.comments[1].startswith(sm.RESULT_MARKER))
        self.assertEqual(len(observed), 1)
        self.assertEqual(len(observed[0]), 1)
        self.assertTrue(observed[0][0].startswith(desktop.STATUS_MARKER))
        # No code, commands or private workspace paths included in the status.
        self.assertNotIn("result.txt", gh.comments[0])
        self.assertNotIn(str(self.root), gh.comments[0])

    def test_rejection_does_not_emit_approval(self):
        gh = FakeGithub(self.task)
        response = desktop.decide(
            self.config, gh, 143, desktop.fingerprint(self.task), False)
        self.assertEqual(response["result"]["status"], "rejected")
        self.assertEqual(len(gh.comments), 1)
        self.assertTrue(gh.comments[0].startswith(sm.RESULT_MARKER))
        self.assertFalse((self.root / "result.txt").exists())

    def test_status_network_failure_does_not_cancel_authorized_work(self):
        gh = FakeGithub(self.task, fail_status=True)
        result = desktop.decide(
            self.config, gh, 143, desktop.fingerprint(self.task), True)
        self.assertTrue(result["ok"])
        self.assertTrue((self.root / "result.txt").is_file())
        self.assertEqual(len(gh.comments), 1)
        self.assertTrue(gh.comments[0].startswith(sm.RESULT_MARKER))

    def test_tampered_issue_never_emits_approval(self):
        gh = FakeGithub({**self.task, "content": "tampered"})
        with self.assertRaisesRegex(ValueError, "Tarefa mudou"):
            desktop.decide(
                self.config, gh, 143, desktop.fingerprint(self.task), True)
        self.assertFalse(gh.comments)
        self.assertFalse((self.root / "result.txt").exists())


if __name__ == "__main__":
    unittest.main()
