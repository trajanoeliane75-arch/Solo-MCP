"""Visual inspection controls and private screenshot transport tests."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import solo_desktop as desktop
import solo_images as images
import solo_inspect as inspect
import solo_mcp as sm


JPEG = b"\xff\xd8\xff" + b"\x12\x34hello" * 1200 + b"\xff\xd9"


class InspectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {
            "control_repo": "owner/private",
            "projects": {"sample": {"path": str(self.root),
                         "permissions": {"read": True, "write": False,
                         "terminal": False, "desktop": True, "environment": False}}}
        }
        self.window = {"version":1, "project":"sample", "action":"inspect_screen", "mode":"window"}
        self.web = {"version":1, "project":"sample", "action":"inspect_screen",
                    "mode":"web", "url":"http://127.0.0.1:3000/"}

    def test_native_mode_needs_consent(self):
        with patch.object(inspect, "inspect_window") as screenshot:
            out = sm.do_task(self.config, self.window, approval_callback=lambda _: False)
        self.assertEqual(out, {"status": "rejected"})
        screenshot.assert_not_called()

    def test_web_mode_needs_consent(self):
        with patch.object(inspect, "inspect_web") as screenshot:
            out = sm.do_task(self.config, self.web, approval_callback=lambda _: False)
        self.assertEqual(out, {"status": "rejected"})
        screenshot.assert_not_called()

    def test_authorized_window_uses_selected_window_backend(self):
        with patch.object(inspect, "inspect_window", return_value=inspect.make_image_result(
            JPEG,"window")) as screenshot:
            out = sm.do_task(self.config, self.window, approval_callback=lambda _: True)
        self.assertIn("_image_b64", out)
        screenshot.assert_called_once()

    def test_authorized_web_uses_new_browser_backend(self):
        with patch.object(inspect, "inspect_web", return_value=inspect.make_image_result(
            JPEG,"web")) as screenshot:
            out = sm.do_task(self.config, self.web, approval_callback=lambda _: True)
        self.assertEqual(out["mode"], "web")
        screenshot.assert_called_once_with("http://127.0.0.1:3000/")

    def test_inspection_denied_without_read_or_desktop(self):
        for caps in ({"read":False,"desktop":True},{"read":True,"desktop":False}):
            with self.subTest(caps=caps):
                self.config["projects"]["sample"]["permissions"].update(caps)
                with patch.object(inspect,"inspect") as backend:
                    with self.assertRaises(PermissionError):
                        sm.do_task(self.config, self.window, approval_callback=lambda _: True)
                    backend.assert_not_called()
                self.config["projects"]["sample"]["permissions"]["read"] = True
                self.config["projects"]["sample"]["permissions"]["desktop"] = True

    def test_background_service_never_attempts_inspect(self):
        class Gh:
            def request(self, method, url, data=None):
                if url == "/repos/owner/private":
                    return {"owner":{"login":"owner"},"private":True}
                if "/issues?" in url:
                    return [{"number":11,"user":{"login":"owner"},
                             "body":sm.MARKER+"\n"+json.dumps(self_task)}]
                raise AssertionError(f"Unexpected remote request: {method} {url}")
        self_task = self.window
        with patch.object(sm,"do_task") as do_task:
            count = sm.process_once(self.config,Gh(),background=True)
        self.assertEqual(count,0)
        do_task.assert_not_called()
        self.assertIn("inspect_screen",sm.MUTATING_ACTIONS)

    def test_only_loopback_web_addresses_are_accepted(self):
        for url in (
            "http://127.0.0.1:3000/",
            "http://localhost:8080/dashboard",
            "http://[::1]:4000/",
        ):
            self.assertEqual(inspect.validate_target({"mode":"web","url":url})["url"],url)
        for url in (
            "https://127.0.0.1:3000/", "https://example.com/",
            "http://example.com:3000/", "http://192.168.1.2:3000/",
            "http://127.0.0.1/", "http://localhost:0/",
            "http://localhost:99999/", "http://user:pass@localhost:3000/",
            "http://localhost:3000/#secret", "file:///etc/passwd",
            "http://localhost:3000/\nattack", "javascript:alert(1)",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                inspect.validate_target({"mode":"web","url":url})

    def test_worker_isolated_playwright_venv_preserves_desktop_python(self):
        venv_dir = self.root / "inspect-venv"
        worker_python = venv_dir / "bin" / "python"
        worker_python.parent.mkdir(parents=True)
        worker_python.write_text("dummy", encoding="utf-8")
        data = inspect.make_image_result(JPEG, "web", {"title":"From venv"})
        mock = subprocess.CompletedProcess([], 0, json.dumps(data), "")
        with patch.object(inspect, "INSPECT_VENV", venv_dir), \
             patch.dict(sys.modules, {"playwright":None, "playwright.sync_api":None}), \
             patch.dict(os.environ, {"SOLO_MCP_TOKEN":"private","OPENAI_API_KEY":"hidden",
                                     "AWS_SECRET_ACCESS_KEY":"aws-key"}), \
             patch.object(inspect.subprocess, "run", return_value=mock) as run:
            result = inspect.inspect_web("http://127.0.0.1:3000/")
        self.assertEqual(result["diagnostics"]["title"],"From venv")
        self.assertEqual(base64.b64decode(result["_image_b64"]),JPEG)
        self.assertEqual(run.call_args.args[0][0],str(worker_python))
        self.assertEqual(run.call_args.args[0][-2],"--web-worker")
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("SOLO_MCP_TOKEN",environment)
        self.assertNotIn("OPENAI_API_KEY",environment)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY",environment)

    def test_missing_playwright_dep_is_explained(self):
        with patch.object(inspect, "INSPECT_VENV", self.root / "absent"), \
             patch.dict(sys.modules, {"playwright":None, "playwright.sync_api":None}):
            with self.assertRaisesRegex(RuntimeError,"Playwright não instalado"):
                inspect.inspect_web("http://127.0.0.1:3000/")

    def test_native_mode_rejects_url(self):
        with self.assertRaises(ValueError):
            inspect.validate_target({"mode":"window","url":"https://example.org"})

    def test_picks_x11_window_interactively_not_arbitrary_remote_id(self):
        picker = subprocess.CompletedProcess([],0,
                                             "xwininfo: Window id: 0x2c0000b \"App\"\n","")
        shot = subprocess.CompletedProcess([],0,JPEG,b"")
        with patch.dict(os.environ, {"DISPLAY":":0","XDG_SESSION_TYPE":"x11"}), \
             patch.object(inspect.shutil, "which", return_value="/usr/bin/bin"), \
             patch.object(inspect.subprocess, "run", side_effect=[picker,shot]) as runner:
            result=inspect.inspect_window()
        self.assertEqual(result["mode"],"window")
        self.assertEqual(runner.call_count,2)
        self.assertEqual(runner.call_args_list[0].args[0],["xwininfo"])
        self.assertEqual(runner.call_args_list[1].args[0][:3],
                         ["import","-window","0x2c0000b"])
        self.assertEqual(base64.b64decode(result["_image_b64"]),JPEG)

    def test_wayland_safely_refused_without_full_desktop(self):
        with patch.dict(os.environ, {"DISPLAY":":0","XDG_SESSION_TYPE":"wayland"}), \
             patch.object(inspect.subprocess, "run") as runner:
            with self.assertRaisesRegex(RuntimeError,"Wayland"):
                inspect.inspect_window()
        runner.assert_not_called()

    def test_no_display_refuses_capture(self):
        with patch.dict(os.environ, {"DISPLAY":""}), \
             patch.object(inspect.subprocess, "run") as runner:
            with self.assertRaisesRegex(RuntimeError,"DISPLAY"):
                inspect.inspect_window()
        runner.assert_not_called()

    def test_malformed_capture_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError,"JPEG inválida"):
            inspect.make_image_result(b"not an image","web")
        with self.assertRaisesRegex(RuntimeError,"grande demais"):
            inspect.make_image_result(b"\xff\xd8\xff" + b"a" * 500000,"web")

    def test_description_warns_of_private_github_storage(self):
        self.assertIn("PRIVADO",inspect.describe_target(self.window))
        self.assertIn("PRIVADO",inspect.describe_target(self.web))
        self.assertIn("nova sessão",inspect.describe_target(self.web))


class ImageTransportTests(unittest.TestCase):
    def test_chunks_are_bounded_and_restore_exact_bytes(self):
        result={"ok":True,"result":inspect.make_image_result(JPEG,"window")}
        safe,chunks=images.make_chunks(result)
        self.assertNotIn("_image_b64",str(safe))
        self.assertEqual(safe["result"]["image"]["bytes"],len(JPEG))
        self.assertEqual(safe["result"]["image"]["parts"],len(chunks))
        self.assertTrue(all(x.startswith(images.IMAGE_MARKER+"\n") for x in chunks))
        restored=images.restore_comments([{"body":b} for b in chunks],
                                        safe["result"]["image"]["sha256"])
        self.assertEqual(restored,JPEG)

    def test_multiple_chunks_check_sha(self):
        jpeg=b"\xff\xd8\xff" + os.urandom(58000)
        safe,chunks=images.make_chunks({"ok":True,"result":inspect.make_image_result(jpeg,"web")})
        self.assertGreater(len(chunks),2)
        target=safe["result"]["image"]["sha256"]
        self.assertEqual(images.restore_comments([{"body":x} for x in chunks],target),jpeg)
        with self.assertRaisesRegex(ValueError,"incompleta"):
            images.restore_comments([{"body":x} for x in chunks[:-1]],target)
        damaged=list(chunks)
        one=json.loads(damaged[0].split("\n",1)[1])
        one["data"]="AAAA"+one["data"][4:]
        damaged[0]=images.IMAGE_MARKER+"\n"+json.dumps(one)
        with self.assertRaisesRegex(ValueError,"SHA-256"):
            images.restore_comments([{"body":x} for x in damaged],target)

    def test_publishing_sends_image_before_final_result_marker(self):
        class Gh:
            def __init__(self):
                self.calls=[]
            def request(self,method,url,data=None):
                self.calls.append((method,url,data))
                return {}
        gh=Gh()
        image=inspect.make_image_result(JPEG,"web",{"title":"Test app"})
        out=sm.publish_task_result(gh,"/repos/owner/private/issues/42",
                                   {"ok":True,"result":image})
        self.assertNotIn("_image_b64",str(out))
        comments=[r[2]["body"] for r in gh.calls if r[0]=="POST"]
        self.assertTrue(comments[0].startswith(images.IMAGE_MARKER))
        self.assertTrue(comments[-1].startswith(sm.RESULT_MARKER))
        self.assertEqual(gh.calls[-1][0],"PATCH")
        self.assertEqual(gh.calls[-1][2],{"state":"closed"})

    def test_rejected_task_never_sends_image(self):
        class Gh:
            def __init__(self):
                self.calls=[]
            def request(self,method,url,data=None):
                self.calls.append((method,url,data))
                return {}
        gh=Gh()
        sm.publish_task_result(gh,"/repos/owner/private/issues/1",
                               {"ok":True,"result":{"status":"rejected"}})
        self.assertEqual([x[0] for x in gh.calls],["POST","PATCH"])
        self.assertTrue(gh.calls[0][2]["body"].startswith(sm.RESULT_MARKER))

    def test_desktop_publishes_image_and_returns_only_metadata(self):
        task={"version":1,"project":"sample","action":"inspect_screen","mode":"window"}
        config={"control_repo":"owner/private","projects":{}}
        bodies=[]
        class Gh:
            def request(self,method,url,data=None):
                if url=="/repos/owner/private":
                    return {"private":True,"owner":{"login":"owner"}}
                if method=="GET" and url.endswith("/issues/16"):
                    return {"state":"open","user":{"login":"owner"},
                            "body":sm.MARKER+"\n"+json.dumps(task)}
                if method=="GET" and "/comments?" in url:return []
                if method=="POST":
                    bodies.append(data["body"])
                    return {}
                if method=="PATCH":return {}
                raise AssertionError((method,url))
        with patch.object(sm,"do_task",return_value=inspect.make_image_result(JPEG,"window")):
            done=desktop.decide(config,Gh(),16,desktop.fingerprint(task),True)
        self.assertNotIn("_image_b64",str(done))
        self.assertTrue(bodies[0].startswith(images.IMAGE_MARKER))
        self.assertTrue(bodies[-1].startswith(sm.RESULT_MARKER))


if __name__=="__main__":
    unittest.main()
