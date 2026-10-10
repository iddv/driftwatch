"""Oversized numeric version field must not crash.

Expected: no 500 (rejected as stale / validation error)
Source: "convention (invalid and extreme input)"
"""

from _helpers.driver import *


def test_x1():
    with Site() as s:
        v = s.add_vendor("A")
        big = "99999999999999999999999"
        for p, d in [(f"/vendors/{v}/archive", {}), (f"/vendors/{v}/restore", {}), (f"/vendors/{v}/edit", {"name": "B", "category": "other"})]:
            st, h, b = s.admin.post(p, version=big, **d)
            assert st < 500, (p, st)
