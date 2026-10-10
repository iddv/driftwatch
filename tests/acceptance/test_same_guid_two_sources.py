"""Same GUID in two sources.

Expected: Each source gets its own entry (deduplication is per source)
Source: "The deduplication key is unique per source"
"""

from _helpers.driver import *

def test_same_guid_two_sources():
    with Site() as s:
        v = s.add_vendor("A"); it = [("same", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")]
        s.fixture("a.xml", rss(it)); s.fixture("b.xml", rss(it))
        a = s.fsource(v, "a.xml", "rss"); b = s.fsource(v, "b.xml", "rss")
        assert len(s.entries(a)) == 1 and len(s.entries(b)) == 1
