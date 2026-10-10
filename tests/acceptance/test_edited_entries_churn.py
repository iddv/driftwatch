"""Edited entries in churn.

Expected: true: edited counts (10); false: excluded (5), still listed
Source: "operator setting churn.count_edited"
Runs with the operator setting `churn.count_edited` = `false` (environment variable CHURN_COUNT_EDITED).
"""

import pytest as _pytest_setting


@_pytest_setting.fixture(autouse=True)
def _operator_setting(monkeypatch):
    monkeypatch.setenv('CHURN_COUNT_EDITED', 'false')


from _helpers.driver import *

def test_edited_entries_churn(monkeypatch):
    monkeypatch.setenv("CHURN_COUNT_EDITED", "false")
    with Site() as s:
        set_clock("2026-10-10T00:00:00Z")
        v = s.add_vendor("W2"); d = "Mon, 05 Oct 2026 00:00:00 GMT"
        s.fixture("w2.xml", rss([("g", "removed thing", d, "v1")])); x = s.fsource(v, "w2.xml", "rss")
        s.fixture("w2.xml", rss([("g", "removed thing", d, "v2")])); s.fetch(x)
        assert len(s.entries(x)) == 2 and s.entries(x)[1]["kind"] == "edited"
        rows = s.admin.get("/churn.csv?months=3")[2].lstrip("\ufeff").splitlines()
        hdr = rows[0].split(","); r = rows[1].split(",")
        assert r[hdr.index("2026-10")] == "5", r
        assert "removed thing" in s.admin.get("/timeline")[2]
