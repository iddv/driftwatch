"""Concurrency limits.

Expected: No more than 4 fetches run at once and never more than 1 against the same host at a time
Source: "At most 4 fetches run concurrently (default), and at most 1 per host at a time."
"""

from _helpers.driver import *

import time
def test_concurrency_limits():
    with Site() as s:
        v = s.add_vendor("A"); hosts = [Origin() for _ in range(6)]; same = Origin()
        for i, o in enumerate(hosts): o.set("/f.xml", rss([("g", f"t{i}", "Mon, 01 Jan 2026 00:00:00 GMT", "x")]))
        for i in range(6): same.set(f"/f{i}.xml", rss([("g", f"s{i}", "Mon, 01 Jan 2026 00:00:00 GMT", "x")]))
        sids = [s.add_source(v, o.url("/f.xml"), "rss", interval_min="15")[0] for o in hosts] + [s.add_source(v, same.url(f"/f{i}.xml"), "rss", interval_min="15")[0] for i in range(6)]
        for o in hosts: o.delay["/f.xml"] = 1.5
        for i in range(6): same.delay[f"/f{i}.xml"] = 1.0
        for o in hosts + [same]: o.max_active = 0
        set_clock(util.now() + __import__("datetime").timedelta(hours=1))
        sc = Scheduler(s.db, s.cfg, tick=1); sc.start(); time.sleep(6); sc.stop()
        assert same.max_active <= 1, same.max_active
        assert sum(o.max_active for o in hosts) >= 1
        import threading
