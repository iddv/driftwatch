"""Feed baseline backfill.

Expected: 10 entries are created marked 'backfill' with their published dates, and they count in churn in the months of those published dates
Source: "For feeds, the first fetch imports existing items as entries marked "backfill" with their published dates. They count in churn by published date."
"""

from _helpers.driver import *

def test_feed_baseline_backfill():
    with Site() as s:
        v = s.add_vendor("A")
        items = [(f"g{i}", f"Removed thing {i}", f"Mon, 0{i} Mar 2026 00:00:00 GMT" if i < 9 else "Mon, 10 Feb 2026 00:00:00 GMT", "x") for i in range(1, 11)]
        items[9] = ("g10", "Removed thing 10", "Tue, 10 Feb 2026 00:00:00 GMT", "x")
        s.fixture("a.xml", rss(items)); sid = s.fsource(v, "a.xml", "rss")
        es = s.entries(sid)
        assert len(es) == 10 and all(e["backfill"] == 1 and e["status"] == "unreviewed" and e["published_at"] for e in es)
        set_clock("2026-04-15T00:00:00Z")
        st, h, b = s.admin.get("/churn.csv")
        assert "A" in b and "50" in b  # 9 in March + 1 in Feb = 10 removals *5 = 50
