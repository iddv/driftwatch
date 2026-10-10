"""Setup accepts 12-char password.

Expected: The admin account is created, the operator is signed in, and an empty Vendors page with an 'Add vendor' button and a note naming the demo command is shown
Source: "Passwords are at least 12 characters (default)."
"""

from _helpers.driver import *

def test_setup_accepts_12_char_password():
    with Site(setup=False) as s:
        c = Client(s.port); t = c.token("/setup")
        st, h, b = c.request("POST", "/setup", {"_csrf": t, "username": "root", "password": "a" * 12, "password2": "a" * 12})
        assert st == 303
        st, h, b = c.get("/vendors")
        assert st == 200 and "Add vendor" in b and "demo load" in b
