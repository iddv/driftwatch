"""Default keywords.

Expected: Suggestions are deprecation, deprecation (listed before removal), removal (listed before scope narrowing), and other respectively
Source: "If no keyword matches, the suggestion is "other". If several categories match, the one listed first wins."
"""

from _helpers.driver import *

def test_default_keywords():
    with Site() as s:
        v = s.add_vendor("A")
        d = "Mon, 01 Jan 2026 00:00:00 GMT"
        s.fixture("a.xml", rss([("0", "seed", d, "x")])); sid = s.fsource(v, "a.xml", "rss")
        s.fixture("a.xml", rss([("0", "seed", d, "x"), ("1", "API SUNSET notice", d, "x"), ("2", "Field removed and deprecated", d, "x"), ("3", "X no longer supported in EU", d, "x"), ("4", "New dashboard", d, "x")])); s.fetch(sid)
        got = {e["title"]: e["suggested_category"] for e in s.entries(sid)}
        assert got["API SUNSET notice"] == "deprecation"
        assert got["Field removed and deprecated"] == "deprecation"
        assert got["X no longer supported in EU"] == "removal"
        assert got["New dashboard"] == "other"
