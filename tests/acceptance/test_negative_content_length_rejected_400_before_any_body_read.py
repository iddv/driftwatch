"""A negative Content-Length is rejected with 400 before any body is read.

Expected: 400 immediately, connection not left reading until EOF
Source: the security review (SECURITY.md).
"""

import socket
from _helpers.driver import Site


def test_negative_content_length_rejected():
    with Site(setup=False) as S:
        s = socket.create_connection(("127.0.0.1", S.port), timeout=5)
        s.sendall(b"POST /login HTTP/1.1\r\nHost: x\r\nContent-Length: -1\r\n\r\nusername=a")
        try:
            data = s.recv(200)
        except socket.timeout:
            data = b"TIMEOUT"
        s.close()
        assert data.startswith(b"HTTP/1.1 400"), data[:60]
