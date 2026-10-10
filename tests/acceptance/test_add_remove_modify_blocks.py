"""Add/remove/modify blocks.

Expected: Three entries are created: one added (after text), one removed (before text), one modified (before and after)
Source: "Each added, removed or modified block becomes a change entry that holds the before and after text."
"""

from _helpers.driver import *

def test_add_remove_modify_blocks():
    with Site() as s:
        v = s.add_vendor("A")
        lst = lambda *x: "<html><body><h2>Heading about the release notes</h2><ul>" + "".join(f"<li>{i}</li>" for i in x) + "</ul><p>Stable paragraph that never changes at all here.</p></body></html>"
        s.fixture("p.html", lst("List item number one stays", "List item number two will be removed")); sid = s.fsource(v, "p.html", "html")
        s.fixture("p.html", "<html><body><h2>Heading about the release notes updated significantly</h2><ul><li>List item number one stays</li></ul><p>Stable paragraph that never changes at all here.</p><p>A brand new paragraph that was added later.</p></body></html>"); s.fetch(sid)
        es = {e["kind"]: e for e in s.entries(sid)}
        assert set(es) == {"added", "removed", "modified"}, [e["kind"] for e in s.entries(sid)]
        assert "brand new" in es["added"]["text_after"] and not es["added"]["text_before"]
        assert "number two" in es["removed"]["text_before"] and not es["removed"]["text_after"]
        assert "Heading about" in es["modified"]["text_before"] and "updated significantly" in es["modified"]["text_after"]
