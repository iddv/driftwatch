import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from .helpers import AppCase, rss


class RobotsFailing(AppCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b"User-agent: *\nDisallow: /" if self.path == "/robots.txt" else b"x"
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

            def log_message(self, *a):
                pass
        cls.rsrv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=cls.rsrv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.rsrv.shutdown()
        super().tearDownClass()

    def _failing_after_first_block(self, name):
        self.allow_loopback()
        vid = self.add_vendor(name)
        url = f"http://127.0.0.1:{self.rsrv.server_address[1]}/{name}.xml"
        s, h, b = self.admin.post(f"/vendors/{vid}/sources/new", url=url, type="rss", interval_min="60", save_anyway="1")
        sid = int(h["Location"].rsplit("/", 1)[1])
        return sid, self.db.val("SELECT failing FROM sources WHERE id=?", (sid,))

    def test_default_true_immediate(self):
        self.assertEqual(self._failing_after_first_block("S3a")[1], 1)

    def test_false_uses_threshold(self):
        self.db.set_setting("fetch.robots_block_fails_immediately", "false")
        self.addCleanup(self.db.set_setting, "fetch.robots_block_fails_immediately", "true")
        sid, failing = self._failing_after_first_block("S3b")
        self.assertEqual(failing, 0)
        for _ in range(2):
            self.admin.post(f"/sources/{sid}/fetch")
        self.assertEqual(self.db.val("SELECT failing FROM sources WHERE id=?", (sid,)), 1)

    def test_env(self):
        with mock.patch.dict(os.environ, {"FETCH_ROBOTS_BLOCK_FAILS_IMMEDIATELY": "false"}):
            self.assertEqual(self._failing_after_first_block("S3c")[1], 0)
