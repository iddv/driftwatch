"""Reorder feed.

Expected: No duplicate entries are created
Source: "The deduplication key is unique per source, so re-fetching cannot create duplicates."
"""

from _helpers.driver import *

def test_reorder_feed():
    with Site() as s:
        v = s.add_vendor("A"); it = [(f"g{i}", f"t{i}", "Mon, 01 Jan 2026 00:00:00 GMT", "x") for i in range(4)]
        s.fixture("a.xml", rss(it)); sid = s.fsource(v, "a.xml", "rss")
        for k in range(3):
            it = it[1:] + it[:1]
            s.fixture("a.xml", rss(it) + "<!-- %d -->" % k); s.fetch(sid)
        assert len(s.entries(sid)) == 4
