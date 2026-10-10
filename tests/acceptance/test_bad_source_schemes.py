"""Bad source schemes.

Expected: A field error is shown, the source is not saved, and no outbound request is made
Source: "Invalid URL, or a scheme other than http or https: a field error is shown."
"""

from _helpers.driver import *

def test_bad_source_schemes():
    with Site() as s:
        o = Origin(); v = s.add_vendor("A")
        for u in ["ftp://x/y", "file:///etc/passwd", "javascript:alert(1)", "http://", "not a url", "http://[bad"]:
            sid, st, b = s.add_source(v, u, "rss", expect=None)
            assert st == 400, (u, st)
        assert s.db.val("select count(*) from sources") == 0
        assert o.hits == []
