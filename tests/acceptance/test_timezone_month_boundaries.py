"""Timezone month boundaries.

Expected: The first counts in April; the second counts in May (its detection month)
Source: "Month boundaries follow the display time zone."
"""

from _helpers.driver import *

def test_timezone_month_boundaries():
    with Site(timezone="Europe/Berlin") as s:
        v = s.add_vendor("A")
        s.fixture("a.xml", rss([("1", "Removed x", "Tue, 31 Mar 2026 23:00:00 GMT", "x")]))
        set_clock("2026-05-10T10:00:00Z")
        sid = s.fsource(v, "a.xml", "rss")
        s.fixture("a.xml", '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title><item><title>Removed y</title><guid>2</guid></item>' + "</channel></rss>")
        s.fixture("b.xml", '<?xml version="1.0"?><rss version="2.0"><channel><title>t</title><item><title>Removed y</title><guid>2</guid></item></channel></rss>')
        sid2 = s.fsource(v, "b.xml", "rss")
        csvt = s.admin.get("/churn.csv?months=6")[2].lstrip("﻿").splitlines()
        hdr = csvt[0].split(","); row = csvt[1].split(",")
        assert row[hdr.index("2026-04")] == "5" and row[hdr.index("2026-03")] == "0" and row[hdr.index("2026-05")] == "5", (hdr, row)
