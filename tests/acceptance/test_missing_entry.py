"""Missing entry.

Expected: A 404 page with a link back to the queue; no server error
Source: "Entry not found (bad link): a 404 page with a link back to the queue."
"""

from _helpers.driver import *

def test_missing_entry():
    with Site() as s:
        for p in ["/entries/99999", "/entries/abc", "/entries/-1"]:
            st, h, b = s.admin.get(p)
            assert st == 404 and 'href="/triage"' in b, (p, st)
