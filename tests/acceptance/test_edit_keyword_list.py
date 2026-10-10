"""Edit keyword list.

Expected: It is suggested as deprecation; a viewer cannot edit keyword lists
Source: "Keyword-based category suggestion with an editable keyword list per category"
"""

from _helpers.driver import *

def test_edit_keyword_list():
    with Site() as s:
        st, h, b = s.admin.get("/keywords"); assert st == 200
        import re
        names = re.findall(r'name="([^"]+)"', b); print(names)
        assert "kw:deprecation" in names or any("deprecation" in n for n in names), names
        nm = [n for n in names if "deprecation" in n][0]
        cur = re.search(r'<textarea[^>]*name="%s"[^>]*>(.*?)</textarea>' % re.escape(nm), b, re.S).group(1)
        st, h, b = s.admin.post("/keywords", **{nm: cur.strip() + "\nretire"})
        assert st in (200, 303)
        v = s.add_vendor("A"); d = "Mon, 01 Jan 2026 00:00:00 GMT"
        s.fixture("a.xml", rss([("0", "seed", d, "x")])); sid = s.fsource(v, "a.xml", "rss")
        s.fixture("a.xml", rss([("0", "seed", d, "x"), ("1", "We will retire the old API", d, "x")])); s.fetch(sid)
        assert [e["suggested_category"] for e in s.entries(sid)][-1] == "deprecation"
        vw = s.make_user("vw", "viewer")
        assert vw.post("/keywords", **{nm: "x"})[0] == 403
