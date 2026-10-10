"""Parsers for RSS 2.0, Atom, JSON Feed, GitHub releases and HTML pages (DOM, CSS selectors, block diff)."""
import difflib
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urljoin

from . import util


class ParseError(Exception):
    pass


class FeedItem:
    def __init__(self, guid=None, link=None, title="", published=None, text=""):
        self.guid, self.link, self.title, self.published, self.text = guid, link, title, published, text

    @property
    def key(self):
        if self.guid:
            return self.guid
        if self.link:
            return self.link
        return util.sha256(f"{self.title}|{util.iso(self.published) if self.published else ''}")


# ---------------------------------------------------------------- text helpers
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
_BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "div", "section", "article", "ul", "ol", "table", "tr", "td",
          "th", "pre", "blockquote", "dl", "dt", "dd", "main", "aside", "footer", "header", "br", "hr", "figure",
          "details", "summary", "form", "tbody", "thead"}
_SKIP = {"script", "style", "nav", "noscript", "template", "head"}


class Node:
    __slots__ = ("tag", "attrs", "children", "parent", "text")

    def __init__(self, tag, attrs=None, parent=None, text=None):
        self.tag, self.attrs, self.parent, self.text = tag, attrs or {}, parent, text
        self.children = []


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root")
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        n = Node(tag, {k: (v or "") for k, v in attrs}, self.cur)
        self.cur.children.append(n)
        if tag not in _VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, {k: (v or "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root:
            if n.tag == tag:
                self.cur = n.parent
                return
            n = n.parent

    def handle_data(self, data):
        self.cur.children.append(Node("#text", parent=self.cur, text=data))


def build_dom(html_text: str) -> Node:
    tb = _TreeBuilder()
    tb.feed(html_text)
    tb.close()
    return tb.root


def _iter(node):
    yield node
    for c in node.children:
        if c.tag != "#text":
            yield from _iter(c)


# ---- minimal CSS selector support: tag, #id, .class, [attr], [attr=v], descendant/child combinators, commas


def _parse_compound(s):
    m = re.match(r"^([a-zA-Z][\w-]*|\*)?((?:[#.][\w-]+|\[[^\]]+\])*)$", s)
    if not m:
        raise ValueError(f"unsupported selector: {s!r}")
    tag = m.group(1)
    conds = []
    for part in re.findall(r"[#.][\w-]+|\[[^\]]+\]", m.group(2)):
        if part[0] == "#":
            conds.append(("id", part[1:]))
        elif part[0] == ".":
            conds.append(("class", part[1:]))
        else:
            am = re.match(r"\[\s*([\w:-]+)\s*(?:([~^$*|]?=)\s*[\"']?([^\"'\]]*)[\"']?)?\s*\]", part)
            if not am:
                raise ValueError(f"unsupported selector: {s!r}")
            conds.append(("attr", am.group(1), am.group(2), am.group(3)))
    return (None if tag in (None, "*") else tag.lower()), conds


def _match_compound(node, comp):
    tag, conds = comp
    if tag and node.tag != tag:
        return False
    for c in conds:
        if c[0] == "id":
            if node.attrs.get("id") != c[1]:
                return False
        elif c[0] == "class":
            if c[1] not in node.attrs.get("class", "").split():
                return False
        else:
            _, name, op, val = c
            if name not in node.attrs:
                return False
            have = node.attrs[name]
            if op is None:
                continue
            ok = {"=": have == val, "^=": have.startswith(val), "$=": have.endswith(val), "*=": val in have,
                  "~=": val in have.split(), "|=": have == val or have.startswith(val + "-")}[op]
            if not ok:
                return False
    return True


def parse_selector(sel: str):
    """Return list of alternatives; each is a list of (combinator, compound)."""
    alts = []
    for part in sel.split(","):
        part = part.strip()
        if not part:
            continue
        seq = []
        pieces = re.split(r"(\s*>\s*|\s+)", part)
        comb = " "
        for p in pieces:
            if not p:
                continue
            if p.strip() == ">":
                comb = ">"
            elif p.strip() == "":
                comb = comb if comb == ">" else " "
            else:
                seq.append((comb, _parse_compound(p)))
                comb = " "
        alts.append(seq)
    if not alts:
        raise ValueError("empty selector")
    return alts


def _match_chain(node, seq, idx):
    comb, comp = seq[idx]
    if not _match_compound(node, comp):
        return False
    if idx == 0:
        return True
    prev_comb = comb  # combinator linking seq[idx-1] -> seq[idx] is stored on seq[idx]
    p = node.parent
    if prev_comb == ">":
        return p is not None and p.tag != "#root" and _match_chain(p, seq, idx - 1)
    while p is not None and p.tag != "#root":
        if _match_chain(p, seq, idx - 1):
            return True
        p = p.parent
    return False


def select(root: Node, selector: str):
    alts = parse_selector(selector)
    out = []
    for n in _iter(root):
        if n.tag == "#root":
            continue
        if any(_match_chain(n, seq, len(seq) - 1) for seq in alts):
            out.append(n)
    return out


def extract_blocks(nodes):
    """Normalized text blocks (paragraphs, list items, headings...) from DOM nodes. script/style/nav stripped."""
    blocks, buf = [], []

    def flush():
        t = util.collapse_ws("".join(buf))
        buf.clear()
        if t:
            blocks.append(t)

    def walk(n):
        if n.tag == "#text":
            buf.append(n.text)
            return
        if n.tag in _SKIP:
            return
        blk = n.tag in _BLOCK
        if blk:
            flush()
        for c in n.children:
            walk(c)
        if blk:
            flush()

    for n in nodes:
        walk(n)
    flush()
    return blocks


def html_extract(body: str, selector: str = None):
    """Return (blocks, selector_matched). selector_matched is None when no selector was given."""
    root = build_dom(body)
    matched = None
    nodes = [root]
    if selector and selector.strip():
        try:
            found = select(root, selector.strip())
        except ValueError as exc:
            raise ParseError(str(exc))
        matched = bool(found)
        if found:
            # drop nodes nested in other matches so text is not duplicated
            ids = {id(n) for n in found}
            nodes = [n for n in found if not _has_ancestor_in(n, ids)]
    return extract_blocks(nodes), matched


def _has_ancestor_in(n, ids):
    p = n.parent
    while p is not None:
        if id(p) in ids:
            return True
        p = p.parent
    return False


def html_to_text(s: str) -> str:
    return "\n".join(extract_blocks([build_dom(s or "")]))


def find_feed_links(body: str, base_url: str):
    """Feed autodiscovery: [(url, type)]."""
    out = []
    for n in _iter(build_dom(body)):
        if n.tag == "link" and "alternate" in n.attrs.get("rel", "").lower().split():
            t = n.attrs.get("type", "").lower()
            href = n.attrs.get("href")
            if href and t in ("application/rss+xml", "application/atom+xml", "application/feed+json",
                              "application/json"):
                kind = {"application/rss+xml": "rss", "application/atom+xml": "atom"}.get(t, "jsonfeed")
                out.append((urljoin(base_url, href), kind))
    return out


# ---------------------------------------------------------------- block diff
def _changed_chars(a, b):
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    same = sum(m.size for m in sm.get_matching_blocks())
    return max(len(a), len(b)) - same


def diff_blocks(old, new, noise=20):
    """List of dicts {kind: added|removed|modified, before, after}. Tiny changes (< noise chars) are dropped."""
    out = []
    sm = difflib.SequenceMatcher(None, old, new, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        olds, news = list(old[i1:i2]), list(new[j1:j2])
        if tag == "replace":
            used = set()
            pairs = {}
            for oi, o in enumerate(olds):
                best, bj = 0.0, None
                for nj, nb in enumerate(news):
                    if nj in used:
                        continue
                    r = difflib.SequenceMatcher(None, o, nb, autojunk=False).ratio()
                    if r > best:
                        best, bj = r, nj
                if bj is not None and best >= 0.5:
                    pairs[oi] = bj
                    used.add(bj)
            for oi, o in enumerate(olds):
                if oi in pairs:
                    nb = news[pairs[oi]]
                    if _changed_chars(o, nb) >= noise:
                        out.append({"kind": "modified", "before": o, "after": nb})
                elif len(o) >= noise:
                    out.append({"kind": "removed", "before": o, "after": None})
            for nj, nb in enumerate(news):
                if nj not in used and len(nb) >= noise:
                    out.append({"kind": "added", "before": None, "after": nb})
        elif tag == "delete":
            out += [{"kind": "removed", "before": o, "after": None} for o in olds if len(o) >= noise]
        else:
            out += [{"kind": "added", "before": None, "after": n} for n in news if len(n) >= noise]
    return out


# ---------------------------------------------------------------- feeds
def _strip_ns(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child(el, name):
    for c in el:
        if _strip_ns(c.tag) == name:
            return c
    return None


def _ctext(el, name):
    c = _child(el, name)
    return (c.text or "").strip() if c is not None else ""


def _xml_root(body: bytes):
    # Feeds often use HTML entities XML does not know (&nbsp; ...). Replace unknown named entities.
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    if re.search(r"<!ENTITY", text):
        raise ParseError("XML entity declarations are not accepted")
    known = {"amp", "lt", "gt", "quot", "apos"}
    import html as _h
    text = re.sub(r"&([A-Za-z][A-Za-z0-9]*);",
                  lambda m: m.group(0) if m.group(1) in known else _h.unescape(m.group(0)), text)
    text = re.sub(r"^<\?xml[^>]*encoding=[\"'][^\"']*[\"'][^>]*\?>", "", text.lstrip("﻿ \t\r\n"), count=1)
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        raise ParseError(f"not well-formed XML: {exc}")


def parse_rss(body: bytes):
    root = _xml_root(body)
    if _strip_ns(root.tag) not in ("rss", "RDF"):
        raise ParseError("not an RSS document")
    channel = _child(root, "channel") if _strip_ns(root.tag) == "rss" else root
    if channel is None:
        raise ParseError("RSS document has no channel")
    items = []
    for it in channel:
        if _strip_ns(it.tag) != "item":
            continue
        title = util.collapse_ws(_ctext(it, "title"))
        link = _ctext(it, "link")
        guid = _ctext(it, "guid")
        content = _ctext(it, "encoded") or _ctext(it, "description")
        pub = util.parse_dt(_ctext(it, "pubDate") or _ctext(it, "date"))
        items.append(FeedItem(guid or None, link or None, title, pub, html_to_text(content)))
    return items


def parse_atom(body: bytes):
    root = _xml_root(body)
    if _strip_ns(root.tag) != "feed":
        raise ParseError("not an Atom document")
    items = []
    for e in root:
        if _strip_ns(e.tag) != "entry":
            continue
        link = None
        for l in e:
            if _strip_ns(l.tag) == "link" and l.attrib.get("rel", "alternate") == "alternate":
                link = l.attrib.get("href")
                break
        content_el = _child(e, "content") if _child(e, "content") is not None else _child(e, "summary")
        content = ""
        if content_el is not None:
            if content_el.attrib.get("type") == "xhtml":
                content = ET.tostring(content_el, encoding="unicode", method="html")
            else:
                content = content_el.text or ""
            if content_el.attrib.get("type", "text") == "text":
                content = util.collapse_ws(content) if "<" not in content else content
        pub = util.parse_dt(_ctext(e, "published") or _ctext(e, "updated"))
        text = html_to_text(content) if "<" in content else content.strip()
        items.append(FeedItem(_ctext(e, "id") or None, link, html_to_text(_ctext(e, "title")) or _ctext(e, "title"),
                              pub, text))
    return items


def parse_jsonfeed(body: bytes):
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise ParseError(f"invalid JSON: {exc}")
    if not isinstance(data, dict) or "items" not in data or not isinstance(data["items"], list):
        raise ParseError("not a JSON Feed (no items array)")
    items = []
    for it in data["items"]:
        if not isinstance(it, dict):
            continue
        text = it.get("content_text") or html_to_text(it.get("content_html") or "") or it.get("summary") or ""
        gid = it.get("id")
        items.append(FeedItem(str(gid) if gid not in (None, "") else None, it.get("url"), it.get("title") or "",
                              util.parse_dt(it.get("date_published") or it.get("date_modified")), text))
    return items


def parse_github_api(body: bytes):
    try:
        data = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError as exc:
        raise ParseError(f"invalid JSON: {exc}")
    if not isinstance(data, list):
        raise ParseError("unexpected GitHub API response")
    return [FeedItem(str(r.get("id")), r.get("html_url"), r.get("name") or r.get("tag_name") or "",
                     util.parse_dt(r.get("published_at") or r.get("created_at")), r.get("body") or "")
            for r in data if isinstance(r, dict)]


def sniff_type(body: bytes, content_type: str = ""):
    """Detect feed type from content: 'rss' | 'atom' | 'jsonfeed' | 'html' | None."""
    head = body[:4096].decode("utf-8", errors="replace").lstrip("﻿ \t\r\n")
    low = head.lower()
    if low.startswith("{"):
        try:
            d = json.loads(body.decode("utf-8", errors="replace"))
            if isinstance(d, dict) and "items" in d:
                return "jsonfeed"
        except ValueError:
            pass
        return None
    if re.search(r"<rss[\s>]", low) or re.search(r"<rdf:rdf", low):
        return "rss"
    if re.search(r"<feed[\s>]", low):
        return "atom"
    if "<html" in low or "<!doctype html" in low or "html" in (content_type or "").lower():
        return "html"
    return None


PARSERS = {"rss": parse_rss, "atom": parse_atom, "github": parse_atom, "jsonfeed": parse_jsonfeed}


def parse_feed(kind: str, body: bytes):
    if kind == "github":  # atom by default, API JSON when a token is configured
        if body.lstrip()[:1] in (b"[", b"{"):
            return parse_github_api(body)
        return parse_atom(body)
    return PARSERS[kind](body)
