"""Robots block failing threshold.

Expected: true: failing after 1 block; false: failing only after 3
Source: "operator setting fetch.robots_block_fails_immediately"
Runs with the operator setting `fetch.robots_block_fails_immediately` = `false` (environment variable FETCH_ROBOTS_BLOCK_FAILS_IMMEDIATELY).
"""

import pytest as _pytest_setting


@_pytest_setting.fixture(autouse=True)
def _operator_setting(monkeypatch):
    monkeypatch.setenv('FETCH_ROBOTS_BLOCK_FAILS_IMMEDIATELY', 'false')


from _helpers.driver import *

def test_robots_block_failing_threshold(monkeypatch):
    monkeypatch.setenv("FETCH_ROBOTS_BLOCK_FAILS_IMMEDIATELY", "false")
    with Site() as s:
        o = Origin(); v = s.add_vendor("A")
        o.set("/robots.txt", "User-agent: *\nDisallow: /", ctype="text/plain"); o.set("/f.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")]))
        sid, st, b = s.add_source(v, o.url("/f.xml"), "rss", save_anyway="1")
        fl = lambda: s.db.val("select failing from sources where id=?", (sid,))
        assert s.db.val("select result from fetch_log where source_id=?", (sid,)) == "blocked by robots.txt"
        assert fl() == 0
        s.fetch(sid); 
        if "false" == "false":
            assert fl() == 0
            s.fetch(sid); assert fl() == 1
            assert "failing" in s.admin.get("/vendors")[2].lower()
