"""A non-numeric Content-Length is rejected with 4xx, not a 500.

Expected: 400 response
Source: the security review (SECURITY.md).
"""

import socket
from _helpers.driver import Site


def test_bad_content_length_is_4xx():
    with Site(setup=False) as S:
        s = socket.create_connection(("127.0.0.1", S.port), timeout=5)
        s.sendall(b"POST /login HTTP/1.1\r\nHost: x\r\nContent-Length: abc\r\n\r\n")
        data = s.recv(200)
        s.close()
        assert data.startswith(b"HTTP/1.1 4"), data[:60]
