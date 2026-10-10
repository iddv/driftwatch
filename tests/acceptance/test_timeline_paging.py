"""Timeline paging.

Expected: Page 1 shows the 50 newest, newest first; page 2 shows the oldest one
Source: "It lists all change entries, newest first, 50 per page."
"""

from _helpers.driver import *

def test_timeline_paging():
    with Site() as s:
        v = s.add_vendor("A")
        s.fixture("a.xml", rss([(str(i), f"item number {i:03d}", f"Mon, 01 Jan 2026 00:00:00 GMT" if i else "Mon, 01 Jan 2020 00:00:00 GMT", "x") for i in range(51)])); sid = s.fsource(v, "a.xml", "rss")
        st, h, b = s.admin.get("/timeline"); import re
        assert len(re.findall(r'href="/entries/\d+"', b)) == 50 and "item number 000" not in b
        st, h, b = s.admin.get("/timeline?page=2"); assert len(re.findall(r'href="/entries/\d+"', b)) == 1 and "item number 000" in b
