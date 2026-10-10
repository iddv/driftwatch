"""Test fetch stores nothing.

Expected: The detected type, item count and newest 5 titles are shown; afterwards no source, snapshot or entry exists
Source: "The system fetches the source once without saving anything and shows the detected type, the item count, and the newest 5 titles or extracted text."
"""

from _helpers.driver import *

def test_test_fetch_stores_nothing():
    with Site() as s:
        v = s.add_vendor("A")
        s.fixture("a.xml", rss([(f"g{i}", f"Title number {i}", f"Mon, 0{i} Jan 2026 00:00:00 GMT", "x") for i in range(1, 8)]))
        st, h, b = s.admin.post(f"/vendors/{v}/sources/test", url=s.fixture_url("a.xml"), type="auto", interval_min="360")
        assert st == 200 and "rss" in b.lower() and "7" in b
        assert b.count("Title number") == 5 and "Title number 7" in b and "Title number 1<" not in b
        assert s.db.val("select count(*) from sources") == 0 and s.db.val("select count(*) from snapshots") == 0 and s.db.val("select count(*) from entries") == 0
