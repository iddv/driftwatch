"""Evidence default range.

Expected: A defaults to 2026-03-01..2027-03-01; B defaults to 2025-10-10..2026-10-10
Source: "The date range defaults to the 12 months up to the vendor's renewal date, or up to today if no renewal date is set."
"""

from _helpers.driver import *

def test_evidence_default_range():
    with Site() as s:
        set_clock("2026-10-10T12:00:00Z")
        a = s.add_vendor("A", renewal_date="2027-03-01"); b = s.add_vendor("B")
        fa = s.admin.get(f"/vendors/{a}/evidence")[2]; fb = s.admin.get(f"/vendors/{b}/evidence")[2]
        assert 'value="2026-03-01"' in fa and 'value="2027-03-01"' in fa, re.findall(r'name="(?:from|to)"[^>]*value="([^"]*)"', fa) or re.findall(r'value="(20[^"]*)"', fa)
        assert 'value="2025-10-10"' in fb and 'value="2026-10-10"' in fb, re.findall(r'value="(20[^"]*)"', fb)
