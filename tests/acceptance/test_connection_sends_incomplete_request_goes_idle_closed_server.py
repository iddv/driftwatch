"""A connection that sends an incomplete request and then goes idle is closed by the server within a bounded time.

Expected: server drops the idle connection (socket timeout) within 25 s
Source: the security review (SECURITY.md).
"""

import socket
import time
from _helpers.driver import Site


def test_idle_connection_is_dropped():
    with Site(setup=False) as S:
        s = socket.create_connection(("127.0.0.1", S.port))
        s.sendall(b"GET /login HTTP/1.1\r\nHost: x\r\n")
        s.settimeout(25)
        t = time.time()
        try:
            data = s.recv(100)  # b"" or an error response means the server gave up
        except socket.timeout:
            data = None
        s.close()
        assert data is not None, "server still holding the half-open request after 25 s"
