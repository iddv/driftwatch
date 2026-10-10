"""Html baseline.

Expected: One snapshot is stored and no change entries are created
Source: "For HTML pages, the first snapshot is the baseline and creates no entries."
"""

from _helpers.driver import *

def test_html_baseline():
    with Site() as s:
        v = s.add_vendor("A"); s.fixture("p.html", html("A paragraph that is long enough to count here."))
        sid = s.fsource(v, "p.html", "html")
        assert s.db.val("select count(*) from snapshots where source_id=?", (sid,)) == 1 and len(s.entries(sid)) == 0
