"""Duplicate source url per vendor.

Expected: The first is refused; the second (different vendor) is accepted
Source: "Duplicate source URL on the same vendor: the save is refused."
"""

from _helpers.driver import *

def test_duplicate_source_url_per_vendor():
    with Site() as s:
        a = s.add_vendor("A"); b_ = s.add_vendor("B")
        s.fixture("a.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")]))
        s.fsource(a, "a.xml", "rss")
        sid, st, b = s.add_source(a, s.fixture_url("a.xml"), "rss", expect=None)
        assert st == 400
        sid, st, b = s.add_source(b_, s.fixture_url("a.xml"), "rss", expect=None)
        assert st == 303
