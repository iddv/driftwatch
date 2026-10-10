"""New item on Fetch now.

Expected: Exactly one new 'unreviewed' entry appears with title, published date, link, full text, a suggested category and a link to the new snapshot; snapshot records fetch time, HTTP status and SHA-256
Source: "adding an item to a local fixture feed and clicking "Fetch now" creates exactly one new unreviewed entry with a suggested category"
"""

from _helpers.driver import *

def test_new_item_fetch_now():
    with Site() as s:
        v = s.add_vendor("A"); items = [("g1", "old", "Mon, 01 Jan 2026 00:00:00 GMT", "x")]
        s.fixture("a.xml", rss(items)); sid = s.fsource(v, "a.xml", "rss")
        items.append(("g2", "Feature X is deprecated", "Tue, 02 Feb 2026 00:00:00 GMT", "Full body text of the item"))
        s.fixture("a.xml", rss(items))
        st, h, b = s.fetch(sid)
        es = s.entries(sid)
        assert len(es) == 2
        e = es[1]
        assert e["status"] == "unreviewed" and e["suggested_category"] == "deprecation" and e["title"] == "Feature X is deprecated"
        assert e["published_at"].startswith("2026-02-02") and "Full body text" in e["text_after"] and e["backfill"] == 0 and e["snapshot_id"]
        sn = s.db.one("select * from snapshots where id=?", (e["snapshot_id"],))
        import hashlib
        assert sn["http_status"] == 200 and sn["fetched_at"] and sn["sha256"] == hashlib.sha256(bytes(sn["body"])).hexdigest()
        st, h, b = s.admin.get(f"/entries/{e['id']}")
        assert st == 200 and "Feature X" in b and f"/snapshots/{e['snapshot_id']}" in b
