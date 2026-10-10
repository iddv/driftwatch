"""Unchanged refetch.

Expected: The attempt is logged as 'no change', no new snapshot is stored, and no entries are created
Source: "Unchanged content (same hash): the attempt is logged as "no change" and no snapshot is duplicated."
"""

from _helpers.driver import *

def test_unchanged_refetch():
    with Site() as s:
        v = s.add_vendor("A"); s.fixture("a.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")])); sid = s.fsource(v, "a.xml", "rss")
        s.fetch(sid)
        assert s.db.val("select count(*) from snapshots") == 1 and len(s.entries(sid)) == 1
        assert s.db.val("select result from fetch_log where source_id=? order by id desc limit 1", (sid,)) == "no change"
