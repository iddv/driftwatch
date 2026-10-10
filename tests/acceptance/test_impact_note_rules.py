"""Impact/note rules.

Expected: High without note is refused with a field error; medium without note and high with note are accepted and the entry becomes 'reviewed'
Source: "High impact is chosen with no note: a field error is shown, because a note is required."
"""

from _helpers.driver import *

def test_impact_note_rules():
    with Site() as s:
        v, sid, es = mk(s)
        e = es[0]; ver = e["version"]
        st, h, b = s.admin.post(f"/entries/{e['id']}/triage", category="removal", impact="high", note="", version=str(ver))
        assert st == 400 and "note is required" in b and s.db.val("select status from entries where id=?", (e["id"],)) == "unreviewed"
        st, h, b = s.admin.post(f"/entries/{e['id']}/triage", category="removal", impact="medium", note="", version=str(ver))
        assert st == 303 and s.db.val("select status from entries where id=?", (e["id"],)) == "reviewed"
        e2 = es[1]
        st, h, b = s.admin.post(f"/entries/{e2['id']}/triage", category="removal", impact="high", note="because", version=str(e2["version"]))
        assert st == 303 and s.db.val("select impact from entries where id=?", (e2["id"],)) == "high"
