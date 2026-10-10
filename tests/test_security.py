import socket

from .helpers import AppCase, Client


class RawRequests(AppCase):
    def raw(self, data):
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        s.sendall(data)
        out = s.recv(300)
        s.close()
        return out

    def test_negative_content_length(self):
        out = self.raw(b"POST /login HTTP/1.1\r\nHost: x\r\nContent-Length: -1\r\n\r\nusername=a")
        self.assertTrue(out.startswith(b"HTTP/1.1 400"), out[:60])

    def test_idle_connection_times_out(self):
        from driftwatch import web
        old = web.Handler.timeout
        web.Handler.timeout = 1
        try:
            s = socket.create_connection(("127.0.0.1", self.port))
            s.sendall(b"GET /login HTTP/1.1\r\nHost: x\r\n")
            s.settimeout(10)
            self.assertEqual(s.recv(100)[:0], b"")  # closed (b"") rather than timing out
            s.close()
        finally:
            web.Handler.timeout = old

    def test_non_numeric_content_length(self):
        out = self.raw(b"POST /login HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.1 400"), out[:60])


class Ssrf(AppCase):
    def test_loopback_source_refused(self):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        hits = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200); self.send_header("Content-Length", "6"); self.end_headers(); self.wfile.write(b"SECRET")

            def log_message(self, *a):
                pass
        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        vid = self.add_vendor("Ssrf")
        s, h, b = self.admin.post(f"/vendors/{vid}/sources/test", url=f"http://127.0.0.1:{srv.server_address[1]}/",
                                  type="html", interval_min="360")
        self.assertNotIn("SECRET", b)
        self.assertIn("refused", b)
        self.assertEqual(hits, [])

    def test_private_and_metadata_literals_refused(self):
        from driftwatch import fetcher
        for host in ("10.0.0.1", "192.168.1.1", "169.254.169.254", "172.16.0.1", "[::1]", "[fe80::1]", "0.0.0.0"):
            with self.assertRaises(fetcher.FetchError, msg=host):
                fetcher.fetch(f"http://{host}:9/", self.cfg)

    def test_operator_allow_list(self):
        from driftwatch import fetcher
        self.allow_loopback()
        with self.assertRaises(fetcher.FetchError) as cm:  # allowed, so it gets as far as a connection error
            fetcher.fetch("http://127.0.0.1:1/", self.cfg)
        self.assertIn("connection failed", str(cm.exception))


class Health(AppCase):
    def test_health_is_public(self):
        s, h, b = Client(self.port).get("/health")
        self.assertEqual((s, b), (200, "ok"))
