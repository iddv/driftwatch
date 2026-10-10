"""Stale triage.

Expected: B sees 'Changed by <A> at <time>, reload to see their version' and A's version remains
Source: ""Changed by <user> at <time>, reload to see their version" is shown and nothing is overwritten."
"""

from _helpers.driver import *

def test_stale_triage():
    with Site() as s:
        v, sid, es = mk(s, 1); e = es[0]; eid = e["id"]; ver = str(e["version"])
        a = s.make_user("alice", "analyst"); b_ = s.make_user("bob", "analyst")
        assert a.post(f"/entries/{eid}/triage", category="removal", impact="low", note="", version=ver)[0] == 303
        st, h, b = b_.post(f"/entries/{eid}/triage", category="fix", impact="low", note="", version=ver)
        if st == 303:
            st, h, b = b_.get(h["Location"])
        assert "Changed by alice at" in b and "reload to see their version" in b, b[:200]
        assert s.db.val("select category from entries where id=?", (eid,)) == "removal"
