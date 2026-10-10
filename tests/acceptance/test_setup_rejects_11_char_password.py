"""Setup rejects 11-char password.

Expected: An inline error about password length is shown and no account is created
Source: "The password is too short or the two entries do not match: the form shows an inline error and nothing is created."
"""

from _helpers.driver import *

def test_setup_rejects_11_char_password():
    with Site(setup=False) as s:
        c = Client(s.port); t = c.token("/setup")
        st, h, b = c.request("POST", "/setup", {"_csrf": t, "username": "root", "password": "a" * 11, "password2": "a" * 11})
        b = b.decode()
        assert st == 400 and "at least 12" in b
        assert s.db.val("SELECT COUNT(*) FROM users") == 0
