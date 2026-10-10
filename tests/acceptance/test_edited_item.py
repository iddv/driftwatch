"""Edited item.

Expected: A new entry marked 'edited' is created linking to the original; the original entry's text is unchanged
Source: "An item that comes back with changed text under the same key creates a new "edited" entry that links to the original."
"""

from _helpers.driver import *

def test_edited_item():
    with Site() as s:
        v = s.add_vendor("A")
        s.fixture("a.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "original text")])); sid = s.fsource(v, "a.xml", "rss")
        s.fixture("a.xml", rss([("g", "t", "Mon, 01 Jan 2026 00:00:00 GMT", "changed text")])); s.fetch(sid)
        es = s.entries(sid)
        assert len(es) == 2 and es[1]["kind"] == "edited" and es[1]["edit_of"] == es[0]["id"]
        assert "original text" in es[0]["text_after"] and es[1]["text_after"].endswith("changed text")
