"""Already fetching.

Expected: 'already fetching' is shown and no second fetch runs for that source
Source: ""Fetch now" is clicked while a fetch of that source is running: the user sees "already fetching" and no second fetch starts."
"""

from _helpers.driver import *

import threading, time
def test_already_fetching():
    with Site() as s:
        o = Origin(); v = s.add_vendor("A")
        o.set("/f.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")]))
        sid, st, b = s.add_source(v, o.url("/f.xml"), "rss")
        o.delay["/f.xml"] = 2; n0 = len(o.hits)
        t = threading.Thread(target=lambda: s.fetch(sid)); t.start(); time.sleep(0.7)
        st, h, b = s.fetch(sid)
        st2, h2, b2 = s.admin.get(h["Location"])
        assert "already fetching" in b2.lower()
        st, h, b = s.admin.post(f"/vendors/{v}/fetch")
        st2, h2, b2 = s.admin.get(h["Location"]); assert "already fetching" in b2.lower()
        t.join()
        assert len(o.hits) - n0 == 1
