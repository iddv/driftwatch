"""Noise threshold 19 vs 20 chars.

Expected: The 19-character change creates no entry but a snapshot is still kept; the 20-character change creates one entry with before and after text
Source: "A change of fewer than 20 characters (default) is ignored as noise but kept in the snapshot."
"""

from _helpers.driver import *

def test_noise_threshold_19_vs_20_chars():
    with Site() as s:
        v = s.add_vendor("A")
        base = "This is the base paragraph of the changelog page with plenty of words."
        s.fixture("p.html", html(base, "Other stable paragraph that stays as it is always.")); sid = s.fsource(v, "p.html", "html")
        s.fixture("p.html", html(base + " " + "x" * 18, "Other stable paragraph that stays as it is always.")); s.fetch(sid)  # 19 chars incl space
        assert len(s.entries(sid)) == 0 and s.db.val("select count(*) from snapshots where source_id=?", (sid,)) == 2
        s.fixture("p.html", html(base + " " + "x" * 18 + "y" * 20, "Other stable paragraph that stays as it is always.")); s.fetch(sid)
        assert len(s.entries(sid)) == 1
