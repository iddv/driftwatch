"""Archive hides from churn.

Expected: Hidden while archived (visible under the 'Archived' filter in vendors), shown again with the same scores after restore
Source: "Archiving stops fetching and hides the vendor from the churn report, but keeps all history."
"""

from _helpers.driver import *

def test_archive_hides_churn():
    with Site() as s:
        v, sid, es = mk(s, 2, "deprecated")
        name = s.db.val("select name from vendors where id=?", (v,))
        assert name in s.admin.get("/churn")[2]
        s.admin.post(f"/vendors/{v}/archive", version=str(s.version("vendors", v)))
        assert name not in s.admin.get("/churn")[2] and name not in s.admin.get("/vendors")[2]
        assert name in s.admin.get("/vendors?archived=1")[2]
        s.admin.post(f"/vendors/{v}/restore", version=str(s.version("vendors", v)))
        assert name in s.admin.get("/churn")[2]
        assert s.db.val("select count(*) from entries where vendor_id=?", (v,)) == 3
