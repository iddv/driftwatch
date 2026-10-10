"""Fetch limits.

Expected: Each attempt fails with its reason logged; a body just under 5 MB and a chain of exactly 5 redirects succeed
Source: "Request timeout: 30 s (default). Maximum response size: 5 MB (default). Redirects are followed up to 5 (default)."
"""

from _helpers.driver import *

def test_fetch_limits():
    with Site(fetch_timeout=2) as s:
        o = Origin(); v = s.add_vendor("A")
        feed = lambda pad: rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "x")]) + "<!--" + "a" * pad + "-->"
        o.set("/big.xml", feed(5 * 1024 * 1024 + 10)); o.set("/ok.xml", feed(5 * 1024 * 1024 - 2000))
        o.delay["/slow.xml"] = 4; o.set("/slow.xml", feed(1))
        for i in range(1, 8):
            o.routes[f"/r{i}"] = (302, {"Location": f"/r{i+1}"}, b"")
        o.set("/r8", feed(2))
        o.routes["/r0"] = (302, {"Location": "/r1"}, b"")
        # 5 redirects: /five -> r3..r8 ; build chains explicitly
        def chain(name, n):
            for i in range(n):
                o.routes[f"/{name}{i}"] = (302, {"Location": f"/{name}{i+1}" if i + 1 < n else "/ok.xml"}, b"")
        chain("c5_", 5); chain("c6_", 6)
        res = {}
        for name in ["/big.xml", "/ok.xml", "/slow.xml", "/c5_0", "/c6_0"]:
            sid, st, b = s.add_source(v, o.url(name), "rss", expect=None, save_anyway="1")
            assert st == 303, name
            res[name] = s.db.val("select result from fetch_log where source_id=? order by id limit 1", (sid,))
        assert res["/big.xml"] == "error" and res["/slow.xml"] == "error" and res["/c6_0"] == "error", res
        assert res["/ok.xml"] != "error" and res["/c5_0"] != "error", res
