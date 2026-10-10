import unittest

from driftwatch import parsing, ingest, scoring
from driftwatch.parsing import ParseError

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>
<item><title>A &amp; B</title><guid>g-1</guid><link>https://e.x/1</link><pubDate>Tue, 03 Jun 2025 10:00:00 GMT</pubDate><description>&lt;p&gt;Hello &lt;b&gt;world&lt;/b&gt;&lt;/p&gt;</description></item>
<item><title>No guid</title><link>https://e.x/2</link><pubDate>Wed, 04 Jun 2025 10:00:00 GMT</pubDate></item>
<item><title>Neither</title><pubDate>Wed, 04 Jun 2025 11:00:00 GMT</pubDate></item></channel></rss>"""

ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>x</title>
<entry><id>tag:e,1</id><title>Release 1</title><link rel="alternate" href="https://e.x/r1"/><updated>2025-02-01T10:00:00Z</updated><content type="html">&lt;p&gt;Removed foo&lt;/p&gt;</content></entry></feed>"""

JSONF = b'{"version":"https://jsonfeed.org/version/1.1","items":[{"id":"1","url":"https://e.x/1","title":"T","content_text":"body","date_published":"2025-03-01T00:00:00Z"},{"title":"no id","content_html":"<p>x</p>"}]}'

GH_API = b'[{"id":5,"name":"v1.2","tag_name":"v1.2","html_url":"https://gh/r","body":"notes","published_at":"2025-01-02T03:04:05Z"}]'


class FeedParsing(unittest.TestCase):
    def test_rss(self):
        items = parsing.parse_rss(RSS)
        self.assertEqual([i.key for i in items][:2], ["g-1", "https://e.x/2"])
        self.assertEqual(items[0].title, "A & B")
        self.assertEqual(items[0].text, "Hello world")
        self.assertEqual(items[0].published.isoformat(), "2025-06-03T10:00:00+00:00")
        self.assertEqual(len(items[2].key), 64)  # sha256 of title + published date
        self.assertEqual(items[2].key, parsing.parse_rss(RSS)[2].key)

    def test_atom_and_github(self):
        (i,) = parsing.parse_feed("atom", ATOM)
        self.assertEqual((i.key, i.link, i.text), ("tag:e,1", "https://e.x/r1", "Removed foo"))
        self.assertEqual(len(parsing.parse_feed("github", ATOM)), 1)

    def test_jsonfeed(self):
        items = parsing.parse_jsonfeed(JSONF)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].key, "1")
        self.assertEqual(items[1].text, "x")

    def test_github_api(self):
        (i,) = parsing.parse_feed("github", GH_API)
        self.assertEqual((i.key, i.title, i.text), ("5", "v1.2", "notes"))

    def test_errors(self):
        for fn, body in ((parsing.parse_rss, b"<html>nope"), (parsing.parse_atom, b"{}"), (parsing.parse_jsonfeed, b"<x/>")):
            with self.assertRaises(ParseError):
                fn(body)
        with self.assertRaises(ParseError):
            parsing.parse_rss(b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "b">]><rss><channel/></rss>')

    def test_sniff_and_autodiscovery(self):
        self.assertEqual(parsing.sniff_type(RSS), "rss")
        self.assertEqual(parsing.sniff_type(ATOM), "atom")
        self.assertEqual(parsing.sniff_type(JSONF), "jsonfeed")
        self.assertEqual(parsing.sniff_type(b"<!doctype html><html>"), "html")
        html = '<html><head><link rel="alternate" type="application/atom+xml" href="/feed.xml"></head></html>'
        self.assertEqual(parsing.find_feed_links(html, "https://e.x/blog/"), [("https://e.x/feed.xml", "atom")])


PAGE = """<html><head><script>var a=1</script></head><body><nav>Home Docs</nav><div id="c"><h1>Log</h1>
<ul><li>First   item</li><li>Second item</li></ul><p>Some paragraph text here</p></div><div class="other"><p>Elsewhere</p></div></body></html>"""


class HtmlParsing(unittest.TestCase):
    def test_extract_strips_noise_and_normalizes(self):
        blocks, matched = parsing.html_extract(PAGE)
        self.assertIsNone(matched)
        self.assertEqual(blocks, ["Log", "First item", "Second item", "Some paragraph text here", "Elsewhere"])

    def test_selector(self):
        self.assertEqual(parsing.html_extract(PAGE, "#c li")[0], ["First item", "Second item"])
        self.assertEqual(parsing.html_extract(PAGE, "div.other > p")[0], ["Elsewhere"])
        blocks, matched = parsing.html_extract(PAGE, "#missing")
        self.assertFalse(matched)
        self.assertIn("Elsewhere", blocks)  # falls back to the full page

    def test_diff_added_removed_modified_and_noise(self):
        old = ["Audit logs are retained for 90 days.", "Connections are capped at one hundred for everyone.", "Keep me around here please"]
        new = ["Audit logs are retained for 30 days by default; longer retention needs an add-on.",
               "Connections are capped at one hundred for everyone!", "Keep me around here please",
               "Brand new announcement that is long enough"]
        ch = parsing.diff_blocks(old, new, noise=20)
        self.assertEqual(sorted(c["kind"] for c in ch), ["added", "modified"])  # '.' -> '!' is noise (< 20 chars)
        mod = [c for c in ch if c["kind"] == "modified"][0]
        self.assertEqual(mod["before"], old[0])
        self.assertTrue(mod["after"].startswith("Audit logs"))
        gone = parsing.diff_blocks(["x" * 40, "keep keep keep keep keep"], ["keep keep keep keep keep"])
        self.assertEqual([c["kind"] for c in gone], ["removed"])
        self.assertEqual(parsing.diff_blocks(["short"], []), [])  # tiny removals ignored


class Keywords(unittest.TestCase):
    RULES = [("deprecation", "deprecat"), ("deprecation", "EOL"), ("removal", "removed"), ("breaking change", "breaking"),
             ("default change", "default"), ("security", "CVE")]

    def test_suggestions(self):
        s = ingest.suggest
        self.assertEqual(s(self.RULES, "API DEPRECATED", ""), "deprecation")
        self.assertEqual(s(self.RULES, "x", "the old thing was Removed"), "removal")
        self.assertEqual(s(self.RULES, "Nothing here", "just text"), "other")
        self.assertEqual(s(self.RULES, "Breaking: removed field", ""), "removal")  # first listed wins
        self.assertEqual(s(self.RULES, "geology protocol", ""), "other")  # EOL is a whole-word match
        self.assertEqual(s(self.RULES, "fix for cve-2026-1", ""), "security")


class Scoring(unittest.TestCase):
    W = {"breaking change": 5, "removal": 5, "scope narrowing": 4, "deprecation": 3, "default change": 3, "security": 2,
         "new capability": 0, "fix": 0, "other": 0}
    M = {"low": 1, "medium": 2, "high": 3}

    def e(self, status, category=None, impact=None, sugg="deprecation"):
        return {"status": status, "category": category, "impact": impact, "suggested_category": sugg}

    def test_rules(self):
        c = scoring.entry_counts
        self.assertEqual(c(self.e("reviewed", "removal", "high"), "include_unreviewed", self.W, self.M), ("removal", 15))
        self.assertEqual(c(self.e("reviewed", "security", "medium"), "confirmed_only", self.W, self.M), ("security", 4))
        self.assertEqual(c(self.e("unreviewed"), "include_unreviewed", self.W, self.M), ("deprecation", 3))
        self.assertIsNone(c(self.e("unreviewed"), "confirmed_only", self.W, self.M))
        self.assertIsNone(c(self.e("dismissed", "removal", "high"), "include_unreviewed", self.W, self.M))
        self.assertEqual(c(self.e("reviewed", "fix", "high"), "include_unreviewed", self.W, self.M), ("fix", 0))


if __name__ == "__main__":
    unittest.main()
