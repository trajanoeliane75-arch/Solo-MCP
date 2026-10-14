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


if __name__=="__main__":
    unittest.main()
