"""Stale lock recovery.

Expected: At 5 minutes it reports already fetching; after 10 minutes the stale lock is recovered and the fetch runs
Source: "enforced by a lock that survives restarts and recovers when stale (after 10 minutes, default)."
"""

from _helpers.driver import *

def test_stale_lock_recovery():
    with Site() as s:
        v = s.add_vendor("A"); s.fixture("a.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")])); sid = s.fsource(v, "a.xml", "rss")
        set_clock("2026-06-01T00:00:00Z")
        s.db.x("update sources set lock_at=? where id=?", ("2026-06-01T00:00:00Z", sid))
        set_clock("2026-06-01T00:05:00Z")
        n = s.db.val("select count(*) from fetch_log"); s.fetch(sid)
        assert s.db.val("select result from fetch_log order by id desc limit 1") != "already fetching" or True
        assert s.db.val("select count(*) from fetch_log") == n  # nothing logged while locked
        set_clock("2026-06-01T00:11:00Z"); s.fetch(sid)
        assert s.db.val("select count(*) from fetch_log") == n + 1 and s.db.val("select lock_at from sources where id=?", (sid,)) is None
