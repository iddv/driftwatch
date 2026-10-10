"""Bulk classify and dismiss.

Expected: Each affected entry is updated and gets its own history record; dismissed entries leave the unreviewed queue
Source: "Selects several entries and applies a category or a dismissal in bulk."
"""

from _helpers.driver import *

def test_bulk_classify_dismiss():
    with Site() as s:
        v, sid, es = mk(s, 3)
        sel = [f"{e['id']}:{e['version']}" for e in es]
        st, h, b = s.admin.post("/triage/bulk", action="classify", category="security", impact="low", sel=sel)
        assert st == 303
        assert s.db.val("select count(*) from entries where status='reviewed' and category='security'") == 3
        assert s.db.val("select count(*) from entry_history where action='reviewed'") == 3
        for e in es: s.admin.post(f"/entries/{e['id']}/reopen", version=str(s.version("entries", e["id"])))
        sel = [f"{e['id']}:{s.version('entries', e['id'])}" for e in es[:2]]
        s.admin.post("/triage/bulk", action="dismiss", sel=sel)
        assert s.db.val("select count(*) from entries where status='dismissed'") == 2
        st, h, b = s.admin.get("/triage")
        assert b.count('aria-label="Select entry') == 2
