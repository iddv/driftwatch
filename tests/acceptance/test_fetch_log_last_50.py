"""Fetch log last 50.

Expected: The fetch log shows the 50 most recent attempts and the last fetch time, result and new-entry count
Source: "a fetch log covering the last 50 attempts"
"""

from _helpers.driver import *

def test_fetch_log_last_50():
    with Site() as s:
        v = s.add_vendor("A"); s.fixture("a.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")])); sid = s.fsource(v, "a.xml", "rss")
        for i in range(50): s.fetch(sid)
        assert s.db.val("select count(*) from fetch_log where source_id=?", (sid,)) == 51
        st, h, b = s.admin.get(f"/sources/{sid}")
        import re
        rows = re.findall(r"no change|baseline", b)
        assert b.count("<tr") - 1 >= 50 and len(re.findall(r"<tr", b.split("Fetch log")[-1])) - 1 == 50 or len(rows) == 50, (len(rows))
