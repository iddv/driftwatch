"""Testing/fetching a source cannot reach loopback or private-network services.

Expected: the Test fetch to http://127.0.0.1:<port>/ is refused and the response body is not shown
Source: the security review (SECURITY.md).
"""

import http.server
import threading
from _helpers.driver import Site


def test_source_test_fetch_blocks_internal_addresses():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><body><main><p>INTERNAL-SECRET-DATA in an internal service page</p></main></body></html>")

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with Site() as S:
            vid = S.add_vendor("V")
            s, h, b = S.admin.post(f"/vendors/{vid}/sources/test", url=f"http://127.0.0.1:{srv.server_address[1]}/",
                                   type="html", interval_min="360")
            assert "INTERNAL-SECRET-DATA" not in b
    finally:
        srv.shutdown()
