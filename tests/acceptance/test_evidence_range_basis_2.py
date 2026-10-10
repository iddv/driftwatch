"""Evidence range basis.

Expected: detected: entry detected in range included; published: excluded by old published date
Source: "operator setting export.range_basis"
Runs with the operator setting `export.range_basis` = `published` (environment variable EXPORT_RANGE_BASIS).
"""

import pytest as _pytest_setting


@_pytest_setting.fixture(autouse=True)
def _operator_setting(monkeypatch):
    monkeypatch.setenv('EXPORT_RANGE_BASIS', 'published')


from _helpers.driver import *

def test_evidence_range_basis_2(monkeypatch):
    monkeypatch.setenv("EXPORT_RANGE_BASIS", "published")
    with Site() as s:
        set_clock("2026-10-10T12:00:00Z")
        v = s.add_vendor("W"); s.fixture("w.xml", rss([("g", "Old item", "Wed, 01 Jan 2025 00:00:00 GMT", "x")])); s.fsource(v, "w.xml", "rss")
        st, h, raw = s.admin.request("POST", f"/vendors/{v}/evidence", {"_csrf": s.admin.csrf, "from": "2026-10-01", "to": "2026-10-10", "min_impact": "low", "confirm_empty": "1"})
        assert st == 200
        import json
        n1 = json.loads(unzip(raw)["manifest.json"])["entry_count"]
        st, h, raw = s.admin.request("POST", f"/vendors/{v}/evidence", {"_csrf": s.admin.csrf, "from": "2025-01-01", "to": "2025-01-31", "min_impact": "low", "confirm_empty": "1"})
        n2 = json.loads(unzip(raw)["manifest.json"])["entry_count"]
        assert (n1, n2) == (0, 1), (n1, n2)
