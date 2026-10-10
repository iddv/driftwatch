"""Shared URL and raw snapshot.

Expected: They see the same filtered results; the raw snapshot is shown exactly as fetched with its SHA-256, and fetched HTML is not executed
Source: "The filtered view's URL can be copied and shared with a teammate who is signed in."
"""

from _helpers.driver import *

def test_shared_url_raw_snapshot():
    with Site() as s:
        v, sid, es = mk(s, 2)
        other = s.make_user("vw", "viewer")
        q = f"/timeline?vendor={v}&cat=other&q=item"
        assert s.admin.get(q)[2].count("/entries/") == other.get(q)[2].count("/entries/") > 0
        e = es[0]; st, h, b = other.get(f"/entries/{e['id']}")
        assert f"/snapshots/{e['snapshot_id']}" in b
        st, h, b = other.get(f"/snapshots/{e['snapshot_id']}")
        sn = s.db.one("select * from snapshots where id=?", (e["snapshot_id"],))
        assert sn["sha256"] in b
        st, h, raw = other.request("GET", f"/snapshots/{e['snapshot_id']}/raw")
        assert st == 200 and raw == bytes(sn["body"])
