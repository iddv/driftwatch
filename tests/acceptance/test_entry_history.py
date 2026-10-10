"""Entry history.

Expected: Each change is listed with user and time; after reopen status is 'unreviewed'; the original text is unchanged
Source: "Reopening returns it to "unreviewed", and each change is kept in the entry's history with the user and the time."
"""

from _helpers.driver import *

def test_entry_history():
    with Site() as s:
        v, sid, es = mk(s, 1); e = es[0]; eid = e["id"]; orig = e["text_after"]
        an = s.make_user("anna", "analyst")
        ver = lambda: str(s.version("entries", eid))
        an.post(f"/entries/{eid}/triage", category="removal", impact="low", note="n", version=ver())
        s.admin.post(f"/entries/{eid}/dismiss", reason="noise", version=ver())
        s.admin.post(f"/entries/{eid}/reopen", version=ver())
        assert s.db.val("select status from entries where id=?", (eid,)) == "unreviewed"
        h = s.q("select username, action, ts from entry_history where entry_id=? order by id", (eid,))
        acts = [(r["username"], r["action"]) for r in h]
        assert ("anna", "reviewed") in acts and ("root", "dismissed") in acts and ("root", "reopened") in acts, acts
        st, hh, b = s.admin.get(f"/entries/{eid}")
        assert "anna" in b and "dismissed" in b and "reopened" in b
        assert s.db.val("select text_after from entries where id=?", (eid,)) == orig
