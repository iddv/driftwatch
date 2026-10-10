"""Setup password mismatch.

Expected: An inline mismatch error is shown and no account exists afterwards (the setup page is still offered)
Source: "the two entries do not match: the form shows an inline error and nothing is created"
"""

from _helpers.driver import *

def test_setup_password_mismatch():
    with Site(setup=False) as s:
        c = Client(s.port); t = c.token("/setup")
        st, h, b = c.request("POST", "/setup", {"_csrf": t, "username": "root", "password": "a" * 12, "password2": "b" * 12})
        assert st == 400 and "do not match" in b.decode()
        assert s.db.val("SELECT COUNT(*) FROM users") == 0
        assert c.get("/setup")[0] == 200
