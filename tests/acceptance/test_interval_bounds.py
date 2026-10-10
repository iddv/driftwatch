"""Interval bounds.

Expected: 15 minutes and 7 days are accepted; 14 minutes and 7 days plus 1 minute are refused with a field error; zero, negative and non-numeric values are also refused
Source: "Allowed intervals range from 15 minutes to 7 days."
"""

from _helpers.driver import *

def test_interval_bounds():
    with Site() as s:
        v = s.add_vendor("A")
        for i, name in enumerate(["a", "b", "c", "d", "e", "f", "g"]):
            s.fixture(name + ".xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")]))
        ok = {"15": 303, "10080": 303, "14": 400, "10081": 400, "0": 400, "-5": 400, "abc": 400}
        for (m, exp), n in zip(ok.items(), "abcdefg"):
            sid, st, b = s.add_source(v, s.fixture_url(n + ".xml"), "rss", interval_min=m, expect=None)
            assert st == exp, (m, st)
