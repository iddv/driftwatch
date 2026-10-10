"""Confirmed_only notice.

Expected: Unreviewed entries add nothing to scores and a notice says 2 unreviewed entries are excluded, linking to the triage queue
Source: "a notice gives the count of unreviewed entries that are excluded, with a link to the triage queue."
"""

from _helpers.driver import *

def test_confirmed_only_notice():
    with Site() as s:
        v, sid, es = mk(s, 2, "deprecated")
        set_clock("2026-01-10T00:00:00Z")
        set_settings(s, churn__count_basis="confirmed_only")
        st, h, b = s.admin.get("/churn")
        assert "3 unreviewed entries" in b and 'href="/triage"' in b
        csvt = s.admin.get("/churn.csv")[2].lstrip("﻿").splitlines()
        hdr = csvt[0].split(","); row = csvt[1].split(",")
        assert row[hdr.index("Total")] == "0", row
