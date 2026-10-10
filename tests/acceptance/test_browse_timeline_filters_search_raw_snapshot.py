"""Browse timeline with filters, search, raw snapshot.

Expected: works
Source: "SCOPE F5"
Flow: F5 in SCOPE.md.
"""

from _helpers.driver import *

def test_f5():
    with Site() as s:
        load_demo(s)
        e = s.db.one("select e.*, v.name vn, v.category vc from entries e join vendors v on v.id=e.vendor_id where e.status='unreviewed' and e.suggested_category='deprecation' order by e.id limit 1")
        day = e["eff_at"][:10]
        q = f"/timeline?vendor={e['vendor_id']}&cat=deprecation&from={day}&to={day}&q={e['title'].split()[0]}"
        st, h, b = s.admin.get(q); assert st == 200 and f"/entries/{e['id']}" in b
        n_expected = s.db.val("select count(*) from entries where vendor_id=? and eff_at>=? and eff_at<?", (e["vendor_id"], day + "T00:00:00Z", day + "T23:59:59Z") ) 
        assert 1 <= b.count('href="/entries/') <= n_expected
        st, h, b = s.admin.get(f"/timeline?vendor={e['vendor_id']}"); n = b.count('href="/entries/')
        assert n == min(50, s.db.val("select count(*) from entries where vendor_id=?", (e["vendor_id"],)))
        st, h, b = s.admin.get(f"/entries/{e['id']}"); assert f"/snapshots/{e['snapshot_id']}" in b
        st, h, b = s.admin.get(f"/snapshots/{e['snapshot_id']}"); sn = s.db.one("select * from snapshots where id=?", (e["snapshot_id"],))
        assert st == 200 and sn["sha256"] in b
        st, h, raw = s.admin.request("GET", f"/snapshots/{e['snapshot_id']}/raw"); assert raw == bytes(sn["body"])
        assert "No changes match" in s.admin.get("/timeline?q=qqqzzz")[2]
