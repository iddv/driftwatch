"""Failing threshold.

Expected: It is not 'failing' after 2 failures or after fail-fail-success-fail-fail; it becomes 'failing' with a badge on the Vendors page at the third consecutive failure; a later success clears it
Source: "After 3 consecutive failures (default) the source is marked "failing". The next success clears the status."
"""

from _helpers.driver import *

def test_failing_threshold():
    with Site() as s:
        o = Origin(); v = s.add_vendor("A")
        o.set("/f.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")]))
        sid, st, b = s.add_source(v, o.url("/f.xml"), "rss")
        fl = lambda: s.db.val("select failing from sources where id=?", (sid,))
        def seq(ok):
            if ok: o.set("/f.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")]) + " ")
            else: o.set("/f.xml", "err", status=500)
            s.fetch(sid)
        seq(False); seq(False); assert fl() == 0
        seq(True); seq(False); seq(False); assert fl() == 0
        seq(False); assert fl() == 1
        st, h, b = s.admin.get("/vendors"); assert "failing" in b.lower()
        seq(True); assert fl() == 0
