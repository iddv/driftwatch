"""Anonymous access refused.

Expected: Each request is refused or redirected to sign-in and no data is returned
Source: "There is no anonymous access. Every page and every export requires a signed-in user."
"""

from _helpers.driver import *

def test_anonymous_access_refused():
    with Site() as s:
        v = s.add_vendor("A"); s.fixture("a.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")])); s.fsource(v, "a.xml", "rss")
        sn = s.db.val("SELECT id FROM snapshots LIMIT 1")
        c = Client(s.port)
        for p in ["/timeline", f"/vendors/{v}", "/churn.csv", f"/vendors/{v}/evidence", f"/snapshots/{sn}", f"/snapshots/{sn}/raw", "/churn", "/triage", "/exports/1/download"]:
            st, h, b = c.request("GET", p)
            assert st in (302, 303) and "/login" in h["Location"], (p, st)
        t = c.token("/login")
        st, h, b = c.request("POST", f"/vendors/{v}/evidence", {"_csrf": t, "from": "2026-01-01", "to": "2026-12-31"})
        assert st in (302, 303, 403), st
        assert b"report.html" not in b
