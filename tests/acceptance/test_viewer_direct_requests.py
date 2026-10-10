"""Viewer direct requests.

Expected: Each returns 'Not allowed' and nothing changes; the controls are not shown in the interface
Source: "Roles: enforced on every request, not only by hiding buttons."
"""

from _helpers.driver import *

def test_viewer_direct_requests():
    with Site() as s:
        v = s.add_vendor("A"); s.fixture("a.xml", rss([("g", "t deprecated", "Mon, 01 Jan 2026 00:00:00 GMT", "x")])); sid = s.fsource(v, "a.xml", "rss")
        eid = s.entries(sid)[0]["id"]
        vw = s.make_user("vw", "viewer")
        reqs = [("/vendors/new", dict(name="Z", category="other")), (f"/vendors/{v}/edit", dict(name="Q", category="other", version="1")), (f"/vendors/{v}/archive", dict(version="1")),
                (f"/vendors/{v}/sources/new", dict(url=s.fixture_url("a.xml") + "?x", type="rss", interval_min="60")), (f"/sources/{sid}/fetch", {}), (f"/vendors/{v}/fetch", {}),
                (f"/entries/{eid}/triage", dict(category="removal", impact="low", version="1")), (f"/entries/{eid}/dismiss", dict(version="1")), ("/triage/bulk", dict(action="dismiss", sel=[str(eid)])),
                ("/keywords", dict(x="1")), (f"/sources/{sid}/pause", {})]
        for p, d in reqs:
            st, h, b = vw.post(p, **d)
            assert st == 403 and "Not allowed" in b, (p, st, b[:100])
        assert s.db.val("select count(*) from vendors") == 1 and s.db.val("select status from entries where id=?", (eid,)) == "unreviewed"
        assert vw.get("/vendors/new")[0] == 403 and vw.get("/triage")[0] == 403
        st, h, b = vw.get(f"/vendors/{v}")
        assert "Add source" not in b and "Archive" not in b and "Fetch now" not in b
