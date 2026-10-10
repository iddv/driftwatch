"""Evidence pack for demo vendor.

Expected: zip verifies and audit logged
Source: "SCOPE F7"
Flow: F7 in SCOPE.md.
"""

from _helpers.driver import *

import hashlib, json
def test_f7():
    with Site() as s:
        load_demo(s)
        v = s.db.one("select * from vendors order by id limit 1")["id"]
        st, h, b = s.admin.get(f"/vendors/{v}"); assert f"/vendors/{v}/evidence" in b
        st, h, b = s.admin.get(f"/vendors/{v}/evidence"); assert st == 200 and 'name="from"' in b
        st, h, raw = s.admin.request("POST", f"/vendors/{v}/evidence", {"_csrf": s.admin.csrf, "from": "2024-01-01", "to": "2027-12-31", "min_impact": "low"})
        assert st == 200
        z = unzip(raw); m = json.loads(z["manifest.json"])
        assert m["entry_count"] > 0 and any(n.startswith("snapshots/") for n in z)
        for f in m["files"]: assert hashlib.sha256(z[f["path"]]).hexdigest() == f["sha256"]
        assert "report.html" in z and "entries.csv" in z
        assert hashlib.sha256(z["manifest.json"]).hexdigest() in s.admin.get("/audit?action=export.evidence")[2]
        st, h, b = s.admin.get(f"/vendors/{v}"); x = re.search(r'href="(/exports/\d+/download)"', b); assert x
        assert s.admin.request("GET", x.group(1))[2][:2] == b"PK"
        st, h, b = s.admin.post(f"/vendors/{v}/evidence", **{"from": "2026-05-01", "to": "2026-01-01", "min_impact": "low"}); assert st == 400
