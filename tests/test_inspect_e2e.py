"""Optional real Chromium/Playwright smoke test for Solo-MCP inspection.

Run separately in CI with SOLO_MCP_BROWSER_TESTS=1 after installing Playwright.
"""
import base64
import http.server
import os
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import solo_inspect


class Page(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        payload = (b'<!doctype html><html><head><title>Visual E2E</title></head>'
                   b'<body><h1 id="test">Solo browser smoke test</h1>'
                   b'<script>console.error("solo-web-inspection-error");</script>'
                   b'</body></html>')
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_args):
        pass


@unittest.skipUnless(os.environ.get("SOLO_MCP_BROWSER_TESTS") == "1",
                     "Real browser is an opt-in CI smoke test")
class VisualBrowserSmoke(unittest.TestCase):
    def test_local_page_image_and_console(self):
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1",0),Page)
        worker = threading.Thread(target=httpd.serve_forever,daemon=True)
        worker.start()
        try:
            url=f"http://127.0.0.1:{httpd.server_address[1]}/"
            result=solo_inspect.inspect_web(url)
        finally:
            httpd.shutdown()
            httpd.server_close()
            worker.join(timeout=2)
        self.assertEqual(result["status"],"captured")
        self.assertEqual(result["mode"],"web")
        raw=base64.b64decode(result["_image_b64"],validate=True)
        self.assertTrue(raw.startswith(b"\xff\xd8\xff"))
        self.assertTrue(len(raw)>1000)
        details=result["diagnostics"]
        self.assertEqual(details["title"],"Visual E2E")
        self.assertEqual(details["http_status"],200)
        self.assertIn("Solo browser smoke test",details["body_text"])
        self.assertTrue(any("solo-web-inspection-error" in error
                            for error in details["console_errors"]))


@unittest.skipUnless(os.environ.get("SOLO_MCP_X11_TESTS") == "1",
                     "Native X11 smoke requires Xvfb and ImageMagick")
class NativeWindowSmoke(unittest.TestCase):
    def test_captures_real_tk_window_with_imagemagick(self):
        import tkinter as tk
        import subprocess
        from unittest.mock import patch
        root=tk.Tk()
        try:
            root.title("Solo native capture smoke")
            root.geometry("370x210+100+100")
            tk.Label(root, text="Janela de teste Solo-MCP",
                     font=("Sans", 16, "bold")).pack(pady=35)
            root.update()
            window_id=hex(root.winfo_id())
            original_run=subprocess.run

            def picker_then_real(command, **kwargs):
                if command == ["xwininfo"]:
                    return subprocess.CompletedProcess(
                        command, 0,
                        f'xwininfo: Window id: {window_id} "Solo native capture smoke"\\n',
                        ""
                    )
                return original_run(command, **kwargs)

            with patch.object(solo_inspect.subprocess,"run",side_effect=picker_then_real):
                result=solo_inspect.inspect_window()
            raw=base64.b64decode(result["_image_b64"],validate=True)
            self.assertEqual(result["mode"],"window")
            self.assertTrue(raw.startswith(b"\xff\xd8\xff"))
            self.assertGreater(len(raw),1000)
        finally:
            root.destroy()


if __name__=="__main__":
    unittest.main()
