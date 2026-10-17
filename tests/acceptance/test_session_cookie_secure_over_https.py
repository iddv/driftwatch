"""Session cookie is Secure over HTTPS.

Expected: POST /login carrying X-Forwarded-Proto: https sets a dw_sess cookie with the Secure
attribute; the same login over plain HTTP sets no Secure attribute, so the cookie keeps working on loopback.
Source: SECURITY.md S6 and issue #3: "Add the Secure attribute to the session cookie when the request arrived over HTTPS."
"""

from _helpers.driver import *


def _login_cookie(port, headers):
    c = Client(port)
    tok = c.token("/login")
    st, rh, _ = c.request("POST", "/login", {"_csrf": tok, "username": "root", "password": PW}, headers=headers)
    assert st == 303, st
    return c, rh["Set-Cookie"]


def test_session_cookie_secure_over_https():
    with Site() as s:
        _, cookie = _login_cookie(s.port, {"X-Forwarded-Proto": "https"})
        assert cookie.startswith("dw_sess="), cookie
        assert "Secure" in cookie, "session cookie lacks Secure over HTTPS: " + cookie
        c, cookie = _login_cookie(s.port, {})
        assert "Secure" not in cookie, cookie
        assert c.get("/profile")[0] == 200
