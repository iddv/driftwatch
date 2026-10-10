"""Triage: classify, dismiss, bulk, reopen, history, stale.

Expected: works
Source: "SCOPE F4"
Flow: F4 in SCOPE.md.
"""

from _helpers.driver import *

def test_f4():
    with Site() as s:
        v, sid, es = mk(s, 4, "default")
        an = s.make_user("anna", "analyst")
        st, h, b = an.get("/triage"); assert st == 200 and "default item 1" in b
        assert an.get(f"/triage?vendor={v}&cat=default+change")[0] == 200
        e = es[0]; st, h, b = an.get(f"/entries/{e['id']}")
        assert st == 200 and "default item 1" in b and "Dismiss" in b and 'name="impact"' in b and 'name="note"' in b and "affects" in b.lower()
        assert an.post(f"/entries/{e['id']}/triage", category="default change", impact="medium", note="n", affects_us="1", version=str(e["version"]))[0] == 303
        r = s.db.one("select * from entries where id=?", (e["id"],)); assert r["status"] == "reviewed" and r["affects_us"] == 1
        e2 = es[1]; assert an.post(f"/entries/{e2['id']}/dismiss", reason="typo", version=str(e2["version"]))[0] == 303
        assert s.db.val("select status from entries where id=?", (e2["id"],)) == "dismissed"
        sel = [f"{x['id']}:{x['version']}" for x in es[2:]]
        assert an.post("/triage/bulk", action="classify", category="deprecation", impact="low", sel=sel)[0] == 303
        assert an.post(f"/entries/{e2['id']}/reopen", version=str(s.version("entries", e2["id"])))[0] == 303
        assert s.db.val("select status from entries where id=?", (e2["id"],)) == "unreviewed"
        b = an.get(f"/entries/{e2['id']}")[2]; assert "dismissed" in b and "reopened" in b and "anna" in b
        ver = str(s.version("entries", e["id"])); s.admin.post(f"/entries/{e['id']}/dismiss", version=ver)
        st, h, b = an.post(f"/entries/{e['id']}/triage", category="fix", impact="low", note="", version=ver)
        if st == 303: b = an.get(h["Location"])[2]
        assert "Changed by root at" in b
