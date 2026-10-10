"""Scheduler resumes on startup.

Expected: The scheduler resumes and fetches the overdue sources; all prior data is intact
Source: "Persistence survives restarts. The scheduler resumes on startup."
"""

from _helpers.driver import *

import time, datetime
def test_scheduler_resumes_startup():
    with Site() as s:
        v = s.add_vendor("A"); s.fixture("a.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")])); sid = s.fsource(v, "a.xml", "rss")
        s.fixture("a.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x"), ("h", "new", "Mon, 01 Jan 2026 00:00:00 GMT", "y")]))
        set_clock(util.now() + datetime.timedelta(days=3))
        sc = Scheduler(s.db, s.cfg, tick=1); sc.start()
        try:
            for _ in range(40):
                if len(s.entries(sid)) == 2: break
                time.sleep(0.25)
        finally:
            sc.stop()
        assert len(s.entries(sid)) == 2
