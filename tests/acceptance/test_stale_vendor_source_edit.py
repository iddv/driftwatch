"""Stale vendor/source edit.

Expected: The second save is rejected as stale and does not overwrite the first
Source: "entries, vendors and sources carry a version number. A save made against a stale version is rejected"
"""

from _helpers.driver import *

def test_stale_vendor_source_edit():
    with Site() as s:
        v = s.add_vendor("A"); s.fixture("a.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")])); sid = s.fsource(v, "a.xml", "rss")
        ver = str(s.version("vendors", v))
        st, h, b = s.admin.post(f"/vendors/{v}/edit", name="A1", category="database", version=ver); assert st == 303
        st, h, b = s.admin.post(f"/vendors/{v}/edit", name="A2", category="database", version=ver)
        assert st == 409 and "Changed by" in b and s.db.val("select name from vendors where id=?", (v,)) == "A1"
        sv = str(s.version("sources", sid))
        s.fixture("b.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")]))
        st, h, b = s.admin.post(f"/sources/{sid}/edit", url=s.fixture_url("b.xml"), type="rss", interval_min="60", version=sv); assert st == 303, b[:300]
        st, h, b = s.admin.post(f"/sources/{sid}/edit", url=s.fixture_url("a.xml"), type="rss", interval_min="30", version=sv)
        assert st == 409 and s.db.val("select interval_s from sources where id=?", (sid,)) == 3600
