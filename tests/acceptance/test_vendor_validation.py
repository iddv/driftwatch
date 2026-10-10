"""Vendor validation.

Expected: Each is refused with a field error and nothing is saved; no server error
Source: "Validation before save: URLs, intervals within range, unique names, required notes, valid dates and role values are all checked."
"""

from _helpers.driver import *

def test_vendor_validation():
    with Site() as s:
        for kw in [dict(name="", category="database"), dict(name="X", category="bogus"), dict(name="X", category="database", homepage="not a url"),
                   dict(name="X", category="database", homepage="ftp://x.com"), dict(name="X", category="database", renewal_date="2026-13-45"), dict(name="X", category="database", renewal_date="soon")]:
            st, h, b = s.admin.post("/vendors/new", **kw)
            assert st == 400, (kw, st)
        assert s.db.val("select count(*) from vendors") == 0
