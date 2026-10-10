"""Scheduler skips paused/archived.

Expected: Neither is fetched; active sources past their interval are fetched
Source: "Archiving stops fetching and hides the vendor from the churn report, but keeps all history."
"""

from _helpers.driver import *

def test_scheduler_skips_paused_archived():
    with Site() as s:
        v = s.add_vendor("A"); w = s.add_vendor("B"); s.fixture("a.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")])); s.fixture("b.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "y")])); s.fixture("c.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "z")]))
        a = s.fsource(v, "a.xml", "rss"); b = s.fsource(v, "b.xml", "rss"); c = s.fsource(w, "c.xml", "rss")
        s.admin.post(f"/sources/{b}/pause"); s.admin.post(f"/vendors/{w}/archive", version=str(s.version("vendors", w)))
        set_clock(util.now() + __import__("datetime").timedelta(days=2))
        due = {x["id"] for x in s.sched_due()} if hasattr(s, "sched_due") else None
        sc = Scheduler(s.db, s.cfg); due = {x["id"] for x in sc.due_sources()}
        assert due == {a}, due
