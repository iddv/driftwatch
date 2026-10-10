"""Setup after admin exists.

Expected: The user is redirected to sign-in and no second admin is created
Source: "Someone opens the setup page after an admin exists: they are redirected to sign-in."
"""

from _helpers.driver import *

def test_setup_after_admin_exists():
    with Site() as s:
        c = Client(s.port)
        st, h, b = c.request("GET", "/setup")
        assert st == 303 and "/login" in h["Location"]
        t = c.token("/login")
        st, h, b = c.request("POST", "/setup", {"_csrf": t, "username": "r2", "password": "a" * 12, "password2": "a" * 12})
        assert st == 303 and "/login" in h["Location"]
        assert s.db.val("SELECT COUNT(*) FROM users") == 1
