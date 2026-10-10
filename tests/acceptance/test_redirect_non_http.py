"""Redirect to non-http.

Expected: The redirect is not followed and the attempt fails with a reason
Source: "Outbound fetches go only to http and https URLs."
"""

from _helpers.driver import *

def test_redirect_non_http():
    with Site() as s:
        o = Origin(); v = s.add_vendor("A")
        o.routes["/r"] = (302, {"Location": "file:///etc/passwd"}, b"")
        sid, st, b = s.add_source(v, o.url("/r"), "rss", expect=None, save_anyway="1")
        assert st == 303 and s.db.val("select result from fetch_log where source_id=?", (sid,)) == "error"
        assert s.db.val("select count(*) from snapshots") == 0
