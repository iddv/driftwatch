"""Failed test needs save anyway.

Expected: The exact failure reason is shown; save is refused without the tick and allowed with it
Source: "the exact reason is shown, and saving is still allowed only if the user ticks "save anyway"."
"""

from _helpers.driver import *

def test_failed_test_needs_save_anyway():
    with Site() as s:
        v = s.add_vendor("A")
        url = s.fixture_url("missing.xml")
        st, h, b = s.admin.post(f"/vendors/{v}/sources/test", url=url, type="rss", interval_min="360")
        assert "404" in b
        sid, st, b = s.add_source(v, url, "rss", expect=None)
        assert st != 303 and "404" in b and s.db.val("select count(*) from sources") == 0
        sid, st, b = s.add_source(v, url, "rss", expect=None, save_anyway="1")
        assert st == 303 and s.db.val("select count(*) from sources") == 1
