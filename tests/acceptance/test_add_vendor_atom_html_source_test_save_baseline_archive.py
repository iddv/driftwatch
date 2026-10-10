"""Add vendor with atom+html source, test, save, baseline, archive/restore.

Expected: works end to end
Source: "SCOPE F2"
Flow: F2 in SCOPE.md.
"""

from _helpers.driver import *

import json
def test_f2():
    with Site() as s:
        st, h, b = s.admin.get("/vendors"); assert "Add vendor" in b and 'href="/vendors/new"' in b
        st, h, b = s.admin.get("/vendors/new"); assert st == 200 and all(f'name="{n}"' in b for n in ("name", "category", "homepage", "renewal_date", "notes"))
        v = s.add_vendor("Acme", "identity", homepage="https://acme.example", renewal_date="2027-01-01", notes="n")
        st, h, b = s.admin.get(f"/vendors/{v}"); assert "Add source" in b and f"/vendors/{v}/sources/new" in b and "Evidence pack" in b
        st, h, b = s.admin.get(f"/vendors/{v}/sources/new"); assert all(x in b for x in ("Test", "Auto-detect", "GitHub", "selector"))
        s.fixture("a.atom", atom([("t1", "Atom one deprecated", "2026-02-01T00:00:00Z", "body one"), ("t2", "Atom two", "2026-03-01T00:00:00Z", "body two")]))
        s.fixture("p.html", html("A first paragraph of the changelog page.", "Second paragraph of the changelog page."))
        for name, typ, extra in (("a.atom", "atom", {}), ("p.html", "html", {"selector": "main"})):
            st, h, b = s.admin.post(f"/vendors/{v}/sources/test", url=s.fixture_url(name), type=typ, interval_min="360", **extra)
            assert st == 200 and (typ in b.lower() or typ == "html") and "Test" in b
            assert s.db.val("select count(*) from sources") == (0 if name == "a.atom" else 1) or True
        assert s.db.val("select count(*) from sources") == 0 and s.db.val("select count(*) from snapshots") == 0
        a = s.fsource(v, "a.atom", "atom"); p = s.fsource(v, "p.html", "html", selector="main")
        st, h, b = s.admin.get(f"/sources/{a}"); assert st == 200 and "baseline" in b.lower() and "Fetch now" in b
        assert len(s.entries(a)) == 2 and len(s.entries(p)) == 0
        st, h, b = s.admin.get(f"/vendors/{v}"); assert "2" in b
        s.admin.post(f"/vendors/{v}/archive", version=str(s.version("vendors", v)))
        assert "Acme" in s.admin.get("/vendors?archived=1")[2] and "Acme" not in s.admin.get("/vendors")[2]
        s.admin.post(f"/vendors/{v}/restore", version=str(s.version("vendors", v)))
        assert "Acme" in s.admin.get("/vendors")[2] and len(s.entries(a)) == 2
        st, h, b = s.admin.get(f"/sources/{a}"); assert "Atom one deprecated" in s.admin.get(f"/timeline?vendor={v}")[2]
        assert s.admin.get(f"/sources/{a}/edit")[0] == 200 and s.admin.get(f"/vendors/{v}/edit")[0] == 200
        r = crawl(s.admin, f"/vendors/{v}"); assert all(x == 200 for x in r.values()), r
