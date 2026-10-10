"""Keyless items.

Expected: No duplicates after the second fetch; changing the published date of the key-less item produces a new entry (its key is the hash of title and published date)
Source: "feed item GUID or id. If missing, the link. If both are missing, a SHA-256 of the title and published date."
"""

from _helpers.driver import *

def test_keyless_items():
    with Site() as s:
        v = s.add_vendor("A")
        def feed(d2):
            return ('<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
                    '<item><title>Has link</title><link>http://x/a</link><description>one</description></item>'
                    f'<item><title>No key</title><pubDate>{d2}</pubDate><description>two</description></item></channel></rss>')
        s.fixture("a.xml", feed("Mon, 01 Jan 2026 00:00:00 GMT")); sid = s.fsource(v, "a.xml", "rss")
        assert len(s.entries(sid)) == 2
        s.fixture("a.xml", feed("Mon, 01 Jan 2026 00:00:00 GMT") + " "); s.fetch(sid)
        assert len(s.entries(sid)) == 2
        s.fixture("a.xml", feed("Tue, 02 Jun 2026 00:00:00 GMT")); s.fetch(sid)
        assert len(s.entries(sid)) == 3
