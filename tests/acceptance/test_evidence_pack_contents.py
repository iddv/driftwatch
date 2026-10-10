"""Evidence pack contents.

Expected: The archive holds an HTML report, CSV, referenced raw snapshots and a manifest whose SHA-256 hashes verify; dismissed entries are absent; the audit log records user, vendor, range and manifest hash; the vendor page lists the export
Source: "The export is recorded in the audit log with the user, the vendor, the range and the manifest hash."
"""

from _helpers.driver import *

import hashlib, json
def test_evidence_pack_contents():
    with Site() as s:
        v, sid, es = mk(s, 3, "deprecated")
        e1, e2 = es[0], es[1]
        s.admin.post(f"/entries/{e1['id']}/triage", category="removal", impact="high", note="important note", version=str(e1["version"]))
        s.admin.post(f"/entries/{e2['id']}/dismiss", reason="noise", version=str(e2["version"]))
        vw = s.make_user("vw", "viewer")
        st, h, raw = vw.request("POST", f"/vendors/{v}/evidence", {"_csrf": vw.csrf, "from": "2025-01-01", "to": "2026-12-31", "min_impact": "low"})
        assert st == 200 and raw[:2] == b"PK", raw[:200]
        z = unzip(raw)
        assert {"report.html", "entries.csv", "manifest.json"} <= set(z) and any(n.startswith("snapshots/") for n in z)
        m = json.loads(z["manifest.json"])
        for f in m["files"]:
            assert hashlib.sha256(z[f["path"]]).hexdigest() == f["sha256"], f
        assert {f["path"] for f in m["files"]} >= {"report.html", "entries.csv"}
        rep = z["report.html"].decode(); csvt = z["entries.csv"].decode()
        assert "important note" in rep and "deprecated item 1" in rep and "deprecated item 2" not in rep and "deprecated item 2" not in csvt
        assert "root" in rep
        mh = hashlib.sha256(z["manifest.json"]).hexdigest()
        a = s.admin.get("/audit")[2]
        assert "export.evidence" in a and mh in a
        assert "export" in s.admin.get(f"/vendors/{v}")[2].lower() and "/exports/" in s.admin.get(f"/vendors/{v}")[2]
