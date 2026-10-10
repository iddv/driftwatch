"""Vendor name case uniqueness.

Expected: true: 'acme' refused when 'Acme' exists; false: allowed (exact duplicate still refused)
Source: "operator setting vendors.name_case_insensitive"
Runs with the operator setting `vendors.name_case_insensitive` = `false` (environment variable VENDORS_NAME_CASE_INSENSITIVE).
"""

import pytest as _pytest_setting


@_pytest_setting.fixture(autouse=True)
def _operator_setting(monkeypatch):
    monkeypatch.setenv('VENDORS_NAME_CASE_INSENSITIVE', 'false')


from _helpers.driver import *

def test_vendor_name_case_uniqueness(monkeypatch):
    monkeypatch.setenv("VENDORS_NAME_CASE_INSENSITIVE", "false")
    with Site() as s:
        s.add_vendor("Acme")
        assert s.admin.post("/vendors/new", name="Acme", category="other")[0] == 400
        st, h, b = s.admin.post("/vendors/new", name="acme", category="other")
        assert st == 303, st
        if "false" == "true":
            assert "A vendor with this name exists" in b
        assert s.db.val("select count(*) from vendors") == 2
