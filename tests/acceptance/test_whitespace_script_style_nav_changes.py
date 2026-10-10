"""Whitespace/script/style/nav changes.

Expected: No change entries are created
Source: "Text is normalized: whitespace is collapsed, and script, style and nav content is stripped."
"""

from _helpers.driver import *

def test_whitespace_script_style_nav_changes():
    with Site() as s:
        v = s.add_vendor("A")
        page = lambda ws, sc, nav: f"<html><head><style>{sc}</style></head><body><nav>{nav}</nav><script>{sc}</script><p>This   is  a long enough{ws}paragraph for the diff to see.</p></body></html>"
        s.fixture("p.html", page(" ", "a", "navigation one is here")); sid = s.fsource(v, "p.html", "html")
        s.fixture("p.html", page("\n\n   ", "var changed = 'a very long script change that is big';", "totally different navigation menu items listed")); s.fetch(sid)
        assert len(s.entries(sid)) == 0
