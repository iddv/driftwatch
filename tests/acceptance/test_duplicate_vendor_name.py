"""Duplicate vendor name.

Expected: Save is refused with 'A vendor with this name exists' and a link to the existing vendor; vendor count unchanged
Source: "Duplicate vendor name: "A vendor with this name exists" is shown, with a link to it."
"""

from _helpers.driver import *

def test_duplicate_vendor_name():
    with Site() as s:
        v = s.add_vendor("Acme DB")
        st, h, b = s.admin.post("/vendors/new", name="Acme DB", category="database")
        assert st == 400 and "A vendor with this name exists" in b and f'/vendors/{v}' in b
        assert s.db.val("select count(*) from vendors") == 1
