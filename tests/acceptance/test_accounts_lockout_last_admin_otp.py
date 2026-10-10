"""Accounts: lockout, last admin, OTP.

Expected: 4 failures do not lock; 5 lock the account so the correct password is refused until 15 minutes pass; last-admin deactivation/demotion is refused with 'At least one admin is required'; the new user must change the one-time password before anything else
Source: "5 failed sign-ins lock the account for 15 minutes (default)."
"""

from _helpers.driver import *

def test_accounts_lockout_last_admin_otp():
    with Site() as s:
        set_clock("2026-06-01T10:00:00Z")
        c = Client(s.port)
        for i in range(4): assert c.login("root", "wrong-wrong-1")[0] == 200
        assert c.login("root", PW)[0] == 303
        c = Client(s.port)
        for i in range(5): c.login("root", "wrong-wrong-1")
        st, h, b = c.login("root", PW); assert st == 200 and "locked" in b.lower()
        set_clock("2026-06-01T10:14:00Z"); assert c.login("root", PW)[0] == 200
        set_clock("2026-06-01T10:16:00Z"); assert c.login("root", PW)[0] == 303
        rid = s.db.val("select id from users where username='root'")
        st, h, b = s.admin.post(f"/users/{rid}/deactivate"); st2, h2, b2 = s.admin.get(h["Location"])
        assert "At least one admin is required" in b2 and s.db.val("select active from users where id=?", (rid,)) == 1
        st, h, b = s.admin.post(f"/users/{rid}/role", role="analyst"); st2, h2, b2 = s.admin.get(h["Location"])
        assert "At least one admin is required" in b2 and s.db.val("select role from users where id=?", (rid,)) == "admin"
        st, h, b = s.admin.post("/users/new", username="newbie", role="analyst")
        otp = re.search(r'<code id="otp">([^<]+)</code>', b).group(1)
        n = Client(s.port); assert n.login("newbie", otp)[0] == 303
        for p in ["/vendors", "/timeline", "/churn"]:
            st, h, b = n.request("GET", p); assert st == 303 and "/profile/password" in h["Location"], p
        assert n.post("/vendors/new", name="X", category="other")[0] in (303, 400) and s.db.val("select count(*) from vendors") == 0
