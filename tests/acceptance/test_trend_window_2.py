"""Trend window.

Expected: true: current month counts in trend (up +5); false: last 3 complete months (flat)
Source: "operator setting churn.trend_includes_current_month"
Runs with the operator setting `churn.trend_includes_current_month` = `true` (environment variable CHURN_TREND_INCLUDES_CURRENT_MONTH).
"""

import pytest as _pytest_setting


@_pytest_setting.fixture(autouse=True)
def _operator_setting(monkeypatch):
    monkeypatch.setenv('CHURN_TREND_INCLUDES_CURRENT_MONTH', 'true')


from _helpers.driver import *

def test_trend_window_2(monkeypatch):
    monkeypatch.setenv("CHURN_TREND_INCLUDES_CURRENT_MONTH", "true")
    with Site() as s:
        set_clock("2026-10-10T00:00:00Z")
        v = s.add_vendor("T"); d = "Mon, 05 Oct 2026 00:00:00 GMT"
        s.fixture("t.xml", rss([("g", "removed thing", d, "v1")])); s.fsource(v, "t.xml", "rss")
        rows = s.admin.get("/churn.csv?months=6")[2].lstrip("\ufeff").splitlines()
        hdr = rows[0].split(","); r = rows[1].split(",")
        t = r[hdr.index("Trend")]
        if "true" == "true":
            assert "+5" in t, t
        else:
            assert "+" not in t and t.endswith("0"), t
