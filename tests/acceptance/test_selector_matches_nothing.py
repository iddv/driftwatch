"""Selector matches nothing.

Expected: A warning is shown and the full page body is used for extraction
Source: "Selector matches nothing: a warning is shown and the full page body is used unless the user corrects the selector."
"""

from _helpers.driver import *

def test_selector_matches_nothing():
    with Site() as s:
        v = s.add_vendor("A"); s.fixture("p.html", html("A paragraph that is long enough to show.", "Second paragraph here also."))
        st, h, b = s.admin.post(f"/vendors/{v}/sources/test", url=s.fixture_url("p.html"), type="html", selector="#nothing", interval_min="360")
        assert "matched nothing" in b and "A paragraph that is long" in b
        sid = s.fsource(v, "p.html", "html", selector="#nothing")
        import json
        ex = json.loads(s.db.val("select extract from snapshots where source_id=?", (sid,)))
        assert any("A paragraph" in x for x in ex)
