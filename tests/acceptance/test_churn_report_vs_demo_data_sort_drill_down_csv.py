"""Churn report vs demo data, sort, drill-down, CSV.

Expected: works
Source: "SCOPE F6"
Flow: F6 in SCOPE.md.
"""

from _helpers.driver import *

from datetime import datetime, timezone
def test_f6():
    with Site() as s:
        load_demo(s)
        W = {"breaking change": 5, "removal": 5, "scope narrowing": 4, "deprecation": 3, "default change": 3, "security": 2}
        M = {"low": 1, "medium": 2, "high": 3, None: 1}
        now = util.now(); months = []
        y, m = now.year, now.month
        for i in range(12):
            months.append((y, m)); m -= 1
            if m == 0: y, m = y - 1, 12
        months.reverse()
        exp = {}
        for e in s.q("select e.*, v.name vn from entries e join vendors v on v.id=e.vendor_id where v.archived=0"):
            if e["status"] == "dismissed": continue
            cat = (e["category"] or e["suggested_category"]) if e["status"] == "reviewed" else e["suggested_category"]
            mult = M[e["impact"]] if e["status"] == "reviewed" else 1
            d = datetime.fromisoformat(e["eff_at"].replace("Z", "+00:00"))
            exp.setdefault(e["vn"], {}).setdefault((d.year, d.month), 0)
            exp[e["vn"]][(d.year, d.month)] += W.get(cat, 0) * mult
        st, h, raw = s.admin.request("GET", "/churn.csv"); txt = raw.decode("utf-8-sig")
        import csv, io
        rows = list(csv.DictReader(io.StringIO(txt)))
        assert len(rows) == 8
        for r in rows:
            for (y, m) in months:
                assert int(r[f"{y}-{m:02d}"]) == exp[r["Vendor"]].get((y, m), 0), (r["Vendor"], y, m)
            assert int(r["Total"]) == sum(exp[r["Vendor"]].get(k, 0) for k in months)
        st, h, b = s.admin.get("/churn"); assert st == 200
        tot = [int(x) for x in re.findall(r"<td class=\"num\"><b>(\d+)</b>", b)]; assert tot == sorted(tot, reverse=True)
        tot = [int(x) for x in re.findall(r"<td class=\"num\"><b>(\d+)</b>", s.admin.get("/churn?sort=total&dir=asc")[2])]; assert tot == sorted(tot)
        link = re.findall(r'href="(/timeline\?[^"]+)"', b)[0].replace("&amp;", "&"); assert s.admin.get(link)[0] == 200
        assert s.admin.get("/churn?vcat=database")[2].count('href="/vendors/') == 2
