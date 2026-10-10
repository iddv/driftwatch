"""Malformed feed.

Expected: The attempt is logged as a parse error, the raw body is kept and viewable, and no entries are created
Source: "Unparseable feed: the attempt is logged as a parse error, the raw body is kept for inspection, and no entries are created."
"""

from _helpers.driver import *

def test_malformed_feed():
    with Site() as s:
        v = s.add_vendor("A"); s.fixture("a.xml", "<rss><channel><item><title>x</item>"); 
        sid, st, b = s.add_source(v, s.fixture_url("a.xml"), "rss", expect=None, save_anyway="1")
        assert st == 303
        assert len(s.entries(sid)) == 0
        assert "parse error" in s.db.val("select result from fetch_log where source_id=?", (sid,))
        snap = s.db.one("select * from snapshots where source_id=?", (sid,))
        assert snap and b"<item><title>x" in bytes(snap["body"])
        assert s.admin.get(f"/snapshots/{snap['id']}")[0] == 200
