"""Churn periods.

Expected: Supported values show that many months (default 12); unsupported values are refused or fall back cleanly without error
Source: "for the last 12 months (default; selectable 3, 6, 12 or 24)"
"""

from _helpers.driver import *

def test_churn_periods():
    with Site() as s:
        mk(s, 1)
        for m in (3, 6, 12, 24):
            h = s.admin.get(f"/churn.csv?months={m}")[2].lstrip("﻿").splitlines()[0].split(",")
            assert sum(1 for x in h if re.match(r"\d{4}-\d{2}$", x)) == m
        for m in ("7", "-1", "abc", ""):
            st, hh, b = s.admin.get(f"/churn?months={m}"); assert st == 200
            st, hh, b = s.admin.get(f"/churn.csv?months={m}"); assert st == 200
