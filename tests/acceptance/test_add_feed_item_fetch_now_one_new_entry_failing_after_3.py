"""Add feed item, fetch now, one new entry; failing after 3 attempts.

Expected: works
Source: "SCOPE F3"
Flow: F3 in SCOPE.md.
"""

from _helpers.driver import *

def test_f3():
    with Site() as s:
        v = s.add_vendor("A"); it = [("g1", "old", "Mon, 01 Jan 2026 00:00:00 GMT", "x")]
        s.fixture("a.xml", rss(it)); sid = s.fsource(v, "a.xml", "rss")
        it.append(("g2", "Quota limit reduced", "Mon, 02 Feb 2026 00:00:00 GMT", "x")); s.fixture("a.xml", rss(it))
        st, h, b = s.admin.get(f"/sources/{sid}"); assert 'action="/sources/%s/fetch"' % sid in b
        st, h, b = s.fetch(sid); assert st == 303
        st, h, b = s.admin.get(h["Location"]); assert "1 new entry" in b
        es = s.entries(sid); assert len(es) == 2 and es[1]["status"] == "unreviewed" and es[1]["suggested_category"] == "scope narrowing"
        assert "Quota limit reduced" in s.admin.get("/triage")[2]
        o = Origin(); w = s.add_vendor("B")
        o.set("/f.xml", "nope", status=503)
        bid, st, b = s.add_source(w, o.url("/f.xml"), "rss", save_anyway="1")
        st, h, b = s.admin.get(f"/sources/{bid}"); assert "failing" not in b.lower().replace("not failing", "")
        s.fetch(bid); assert "failing" not in s.admin.get("/vendors")[2].lower()
        s.fetch(bid)
        assert s.db.val("select failing from sources where id=?", (bid,)) == 1
        assert "failing" in s.admin.get("/vendors")[2].lower() and "failing" in s.admin.get(f"/sources/{bid}")[2].lower()
