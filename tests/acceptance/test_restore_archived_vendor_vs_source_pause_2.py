"""Restore of archived vendor vs source pause.

Expected: true: active sources stay active (manually paused stays paused); false: all sources paused
Source: "operator setting vendors.restore_resumes_fetching"
Runs with the operator setting `vendors.restore_resumes_fetching` = `true` (environment variable VENDORS_RESTORE_RESUMES_FETCHING).
"""

import pytest as _pytest_setting


@_pytest_setting.fixture(autouse=True)
def _operator_setting(monkeypatch):
    monkeypatch.setenv('VENDORS_RESTORE_RESUMES_FETCHING', 'true')


from _helpers.driver import *

def test_restore_archived_vendor_vs_source_pause_2(monkeypatch):
    monkeypatch.setenv("VENDORS_RESTORE_RESUMES_FETCHING", "true")
    with Site() as s:
        v = s.add_vendor("A"); s.fixture("a.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")])); s.fixture("b.xml", rss([("g", "u", "Mon, 01 Jan 2026 00:00:00 GMT", "x")]))
        a = s.fsource(v, "a.xml", "rss"); b = s.fsource(v, "b.xml", "rss")
        s.admin.post(f"/sources/{b}/pause")
        s.admin.post(f"/vendors/{v}/archive", version=str(s.version("vendors", v)))
        s.admin.post(f"/vendors/{v}/restore", version=str(s.version("vendors", v)))
        pa = s.db.val("select paused from sources where id=?", (a,)); pb = s.db.val("select paused from sources where id=?", (b,))
        assert pb == 1
        assert pa == 0
        assert s.db.val("select count(*) from entries") == 2
