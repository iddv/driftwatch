"""Churn scoring example.

Expected: The cell score is 15 + 3 + 0 + 0 + 4 = 22
Source: "Impact multiplier: low ×1, medium ×2, high ×3 (default). Unreviewed entries count at ×1. Dismissed entries never count."
"""

from _helpers.driver import *

def test_churn_scoring_example():
    with Site() as s:
        v = s.add_vendor("A"); d = "Mon, 01 Jun 2026 00:00:00 GMT"
        base = [("0", "seed", d, "x")]
        s.fixture("a.xml", rss(base)); sid = s.fsource(v, "a.xml", "rss")
        s.fixture("a.xml", rss(base + [("1", "bk", d, "x"), ("2", "dep ecated deprecation", d, "x"), ("3", "rm", d, "x"), ("4", "nc", d, "x"), ("5", "sec", d, "x")])); s.fetch(sid)
        e = {x["title"]: x for x in s.entries(sid)}
        T = lambda t, **kw: s.admin.post(f"/entries/{e[t]['id']}/triage", version=str(e[t]["version"]), note="n", **kw)
        T("bk", category="breaking change", impact="high"); T("nc", category="new capability", impact="high"); T("sec", category="security", impact="medium")
        s.admin.post(f"/entries/{e['rm']['id']}/dismiss", version=str(e["rm"]["version"]))
        set_clock("2026-06-20T00:00:00Z")
        st, h, b = s.admin.get("/churn.csv?months=3"); lines = b.lstrip("﻿").splitlines()
        row = lines[1].split(","); hdr = lines[0].split(",")
        assert row[hdr.index("2026-06")] == "22", (hdr, row)
