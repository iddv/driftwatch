"""Robots.txt respect.

Expected: The attempt is logged as 'blocked by robots.txt' and no snapshot or entry is created
Source: "Blocked by robots.txt (when `fetch.robots_txt` = respect): the attempt is logged as "blocked by robots.txt""
"""

from _helpers.driver import *

def test_robots_txt_respect():
    with Site() as s:
        o = Origin(); v = s.add_vendor("A")
        o.set("/robots.txt", "User-agent: *\nDisallow: /private/", ctype="text/plain"); o.set("/private/f.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")]))
        sid, st, b = s.add_source(v, o.url("/private/f.xml"), "rss", expect=None, save_anyway="1")
        assert st == 303
        assert s.db.val("select result from fetch_log where source_id=?", (sid,)) == "blocked by robots.txt"
        assert s.db.val("select count(*) from snapshots") == 0 and len(s.entries()) == 0
