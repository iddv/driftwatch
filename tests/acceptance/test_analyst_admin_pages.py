"""Analyst admin pages.

Expected: Each is refused and nothing changes
Source: "Users, settings, audit log, purge | No | No | Yes"
"""

from _helpers.driver import *

def test_analyst_admin_pages():
    with Site() as s:
        an = s.make_user("an", "analyst")
        for p in ["/users", "/settings", "/audit", "/users/new"]:
            assert an.get(p)[0] == 403, p
        assert an.post("/users/new", username="zz", role="viewer")[0] == 403
        assert an.post("/settings", **{"s:triage.suggestions": "auto_apply"})[0] == 403
        assert s.db.val("select count(*) from users where username='zz'") == 0
