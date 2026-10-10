"""Invalid date range / no results.

Expected: The first shows a field error; the second shows 'No changes match' with a clear-filters action
Source: "An invalid date range (start after end): a field error is shown."
"""

from _helpers.driver import *

def test_invalid_date_range_no_results():
    with Site() as s:
        mk(s, 2)
        st, h, b = s.admin.get("/timeline?from=2026-05-01&to=2026-01-01")
        assert "end date must not be before" in b
        st, h, b = s.admin.get("/timeline?q=zzzzqqq")
        assert "No changes match" in b and "Clear filters" in b.replace("clear", "Clear")
