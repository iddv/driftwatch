"""Default interval and baseline.

Expected: Its interval is 6 hours and a baseline fetch has run immediately
Source: "Default interval: 6 hours (default)."
"""

from _helpers.driver import *

def test_default_interval_baseline():
    with Site() as s:
        v = s.add_vendor("A"); s.fixture("a.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")]))
        st, h, form = s.admin.get(f"/vendors/{v}/sources/new")
        assert 'value="360"' in form
        sid, st, b = s.add_source(v, s.fixture_url("a.xml"), "rss", interval_min="360")
        assert s.db.val("select interval_s from sources where id=?", (sid,)) == 6 * 3600
        assert s.db.val("select count(*) from fetch_log where source_id=?", (sid,)) == 1
        assert len(s.entries(sid)) == 1
