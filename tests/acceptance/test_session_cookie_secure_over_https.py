"""Session cookie is Secure over HTTPS.

Expected: A sign-in that arrived through a TLS proxy (X-Forwarded-Proto: https) sets a session cookie with the Secure attribute; a plain-HTTP sign-in on loopback sets one without it, so it still works
Source: SECURITY.md S6 (session cookie lacks Secure); issue #3
"""

from _helpers.driver import *

def _login_cookie(s, headers):
    c = Client(s.port)
    t = c.token("/login")
    st, h, b = c.request("POST", "/login", {"_csrf": t, "username": "root", "password": PW}, headers)
    assert st == 303, st
    return [v for k, v in h.items() if k.lower() == "set-cookie" and v.startswith("dw_sess=")] or [h.get("Set-Cookie", "")]

def test_session_cookie_secure_over_https():
    with Site() as s:
        plain = _login_cookie(s, {})
        assert plain and "Secure" not in plain[0], plain
        https = _login_cookie(s, {"X-Forwarded-Proto": "https"})
        assert "Secure" in https[0], f"session cookie lacks Secure over HTTPS: {https[0]}"
