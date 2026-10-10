"""Churn sort, drill-down, CSV.

Expected: Sorting reorders rows; the cell opens the Timeline filtered to that vendor and month; the CSV matches the displayed table, and each total equals the sum of its entries' scores
Source: "Clicking a cell opens the Timeline (F5) filtered to that vendor and month."
"""

from _helpers.driver import *

def test_churn_sort_drill_down_csv():
    with Site() as s:
        set_clock("2026-06-15T00:00:00Z")
        for n, t in (("Aa", "deprecated"), ("Bb", "plain"), ("Cc", "removed")):
            v = s.add_vendor(n); d = "Mon, 01 Jun 2026 00:00:00 GMT"
            s.fixture(f"{n}.xml", rss([("0", "seed", d, "x")])); sid = s.fsource(v, f"{n}.xml", "rss")
            s.fixture(f"{n}.xml", rss([("0", "seed", d, "x"), ("1", f"{t} thing", d, "x")])); s.fetch(sid)
        st, h, b = s.admin.get("/churn?sort=total&dir=desc")
        names = re.findall(r'href="/vendors/\d+">(\w+)</a>', b); assert names == ["Cc", "Aa", "Bb"], names
        names = re.findall(r'href="/vendors/\d+">(\w+)</a>', s.admin.get("/churn?sort=total&dir=asc")[2]); assert names[-1] == "Cc"
        names = re.findall(r'href="/vendors/\d+">(\w+)</a>', s.admin.get("/churn?sort=deprecation&dir=desc")[2]); assert names[0] == "Aa"
        m = re.search(r'href="(/timeline\?[^"]*2026-06-01[^"]*)"', b.replace("&amp;", "&")); assert m
        st, h, tb = s.admin.get(m.group(1)); assert st == 200 and "thing" in tb
        rows = s.admin.get("/churn.csv?months=6")[2].lstrip("﻿").splitlines()
        hdr = rows[0].split(",")
        for r in rows[1:]:
            c = r.split(","); assert sum(int(c[i]) for i, x in enumerate(hdr) if re.match(r"\d{4}-\d{2}$", x)) == int(c[hdr.index("Total")])
        tot = {r.split(",")[0]: r.split(",")[hdr.index("Total")] for r in rows[1:]}
        assert tot == {"Cc": "5", "Aa": "3", "Bb": "0"}
