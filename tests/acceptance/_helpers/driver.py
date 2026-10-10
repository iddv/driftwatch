"""Thin helpers over Driftwatch's real HTTP interface; in-process server, injected clock via driftwatch.util.set_now."""
import os as _os
# These helpers find the repository from their own location. They live in
# tests/acceptance/_helpers/; paths are computed as if they sat one level below
# the repository root.
_HERE = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))), '_helpers', 'driver.py')
import http.client
import io
import json
import re
import sys
import tempfile
import threading
import zipfile
from datetime import datetime, timezone
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(_HERE).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from driftwatch import config, web, util  # noqa: E402
from driftwatch.db import Database  # noqa: E402
from driftwatch.scheduler import Scheduler  # noqa: E402

PW = "a-long-password-1"


def set_clock(dt):
    """dt: aware datetime or ISO string or None (real clock)."""
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    util.set_now(dt)


def reset_clock():
    util.set_now(None)


class Client:
    def __init__(self, port):
        self.port, self.cookies, self.csrf = port, {}, None

    def request(self, method, path, data=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        h = {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}
        h.update(headers or {})
        body = None
        if data is not None:
            body = urlencode(data, doseq=True)
            h["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body, h)
        r = conn.getresponse()
        raw = r.read()
        for k, v in r.getheaders():
            if k.lower() == "set-cookie":
                for ck, m in SimpleCookie(v).items():
                    if m.value:
                        self.cookies[ck] = m.value
                    else:
                        self.cookies.pop(ck, None)
        conn.close()
        return r.status, dict(r.getheaders()), raw

    def get(self, path):
        s, h, b = self.request("GET", path)
        return s, h, b.decode("utf-8", "replace")

    def token(self, path="/login"):
        s, h, b = self.get(path)
        m = re.search(r'name="_csrf" value="([^"]+)"', b)
        return m.group(1) if m else None

    def post(self, path, **data):
        data["_csrf"] = self.csrf or self.token("/login")
        s, h, b = self.request("POST", path, data)
        return s, h, b.decode("utf-8", "replace")

    def login(self, user, pw):
        tok = self.token("/login")
        s, h, b = self.request("POST", "/login", {"_csrf": tok, "username": user, "password": pw})
        self.csrf = (self.token("/profile") or self.token("/profile/password")) if s == 303 else None
        return s, h, b.decode("utf-8", "replace")


class Site:
    """A running Driftwatch with a throw-away data dir; .admin is a signed-in admin Client."""

    def __init__(self, setup=True, scheduler=False, **cfgover):
        reset_clock()
        self.tmp = tempfile.TemporaryDirectory()
        cfg = config.load(env={})
        cfg.data_dir = Path(self.tmp.name)
        cfg.port = 0
        cfg.fetch_timeout = 5
        for k, v in cfgover.items():
            setattr(cfg, k, v)
        config.prepare_data_dir(cfg)
        self.db = Database(cfg.db_path)
        self.db.migrate()
        self.app = web.App(self.db, cfg)
        self.srv = web.make_server(self.app, cfg, quiet=True)
        cfg.port = self.srv.server_address[1]
        self.cfg, self.port = cfg, cfg.port
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.sched = None
        if scheduler:
            self.sched = Scheduler(self.db, cfg, tick=1)
            self.app.scheduler = self.sched
        self.admin = Client(self.port)
        if setup:
            tok = self.admin.token("/setup")
            s, _, _ = self.admin.request("POST", "/setup", {"_csrf": tok, "username": "root", "password": PW, "password2": PW})
            assert s == 303, s
            self.admin.csrf = self.admin.token("/profile")

    def close(self):
        reset_clock()
        if self.sched:
            self.sched.stop()
        self.srv.shutdown()
        self.srv.server_close()
        self.db.close()
        self.tmp.cleanup()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # --- helpers
    def fixture(self, name, content):
        (self.cfg.data_dir / "fixtures" / name).write_bytes(content if isinstance(content, bytes) else content.encode())

    def fixture_url(self, name):
        return f"{self.cfg.base_url}/_fixtures/{name}"

    def make_user(self, username, role):
        s, h, b = self.admin.post("/users/new", username=username, role=role)
        assert s == 200, b[:300]
        otp = re.search(r'<code id="otp">([^<]+)</code>', b).group(1)
        c = Client(self.port)
        assert c.login(username, otp)[0] == 303
        newpw = "new-password-for-" + username
        s, h, b = c.post("/profile/password", current=otp, new=newpw, new2=newpw)
        assert s == 303, b[:400]
        c.password = newpw
        c.csrf = c.token("/profile")
        return c

    def add_vendor(self, name, category="database", client=None, **kw):
        s, h, b = (client or self.admin).post("/vendors/new", name=name, category=category, **kw)
        assert s == 303, b[:500]
        return int(h["Location"].rsplit("/", 1)[1])

    def add_source(self, vid, url, stype, client=None, interval_min="360", expect=303, **kw):
        s, h, b = (client or self.admin).post(f"/vendors/{vid}/sources/new", url=url, type=stype, interval_min=interval_min, **kw)
        if expect:
            assert s == expect, (s, b[:800])
        return (int(h["Location"].rsplit("/", 1)[1]) if s == 303 else None), s, b

    def fsource(self, vid, name, stype, **kw):
        sid, s, b = self.add_source(vid, self.fixture_url(name), stype, **kw)
        return sid

    def q(self, sql, args=()):
        return self.db.q(sql, args)

    def entries(self, sid=None):
        if sid:
            return self.q("SELECT * FROM entries WHERE source_id=? ORDER BY id", (sid,))
        return self.q("SELECT * FROM entries ORDER BY id")

    def fetch(self, sid, client=None):
        return (client or self.admin).post(f"/sources/{sid}/fetch")

    def version(self, table, id_):
        return self.db.val(f"SELECT version FROM {table} WHERE id=?", (id_,))


def rss(items):
    """items: (guid, title, pubDate, description)"""
    body = "".join(f"<item><title>{t}</title><guid>{g}</guid><pubDate>{d}</pubDate><description>{x}</description></item>"
                   for g, t, d, x in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{body}</channel></rss>'


def atom(items):
    body = "".join(f"<entry><title>{t}</title><id>{g}</id><updated>{d}</updated><link href=\"http://x/{g}\"/><content>{x}</content></entry>"
                   for g, t, d, x in items)
    return f'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>t</title>{body}</feed>'


def html(*paras):
    return "<html><body><main>" + "".join(f"<p>{p}</p>" for p in paras) + "</main></body></html>"


class Origin:
    """Local HTTP origin with programmable responses: routes[path] = (status, headers, body) or callable(handler)."""

    def __init__(self):
        self.routes, self.hits, self.delay = {}, [], {}
        self.active = 0
        self.max_active = 0
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, *a):
                pass

            def do_GET(self):
                import time
                outer.hits.append(self.path)
                outer.active += 1
                outer.max_active = max(outer.max_active, outer.active)
                try:
                    if self.path in outer.delay:
                        time.sleep(outer.delay[self.path])
                    r = outer.routes.get(self.path.split("?")[0])
                    if r is None:
                        self.send_response(404); self.end_headers(); return
                    if callable(r):
                        r = r(self)
                    st, hd, body = r
                    if isinstance(body, str):
                        body = body.encode()
                    self.send_response(st)
                    for k, v in hd.items():
                        self.send_header(k, v)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                finally:
                    outer.active -= 1

        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.srv.daemon_threads = True
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def set(self, path, body, status=200, ctype="application/xml", headers=None):
        h = {"Content-Type": ctype}
        h.update(headers or {})
        self.routes[path] = (status, h, body)

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


def unzip(data):
    z = zipfile.ZipFile(io.BytesIO(data))
    return {n: z.read(n) for n in z.namelist()}


def mk(s, n=3, title="plain"):
    """Vendor 'A<title>' with an rss source; baseline of one seed item then n new unreviewed entries. Returns (vendor, source, entries)."""
    v = s.add_vendor("A" + title)
    d = "Mon, 01 Jan 2026 00:00:00 GMT"
    s.fixture(f"{title}.xml", rss([("0", "seed", d, "x")]))
    sid = s.fsource(v, f"{title}.xml", "rss")
    s.fixture(f"{title}.xml", rss([("0", "seed", d, "x")] + [(str(i), f"{title} item {i}", d, "x") for i in range(1, n + 1)]))
    s.fetch(sid)
    return v, sid, [e for e in s.entries(sid) if e["title"] != "seed"]


def set_settings(s, **kv):
    """Admin posts the Settings form with the given overrides, keys given with '__' for '.' (e.g. churn__count_basis)."""
    cur = s.db.all_settings()
    for k, v in kv.items():
        cur[k.replace("__", ".")] = v
    st, h, b = s.admin.post("/settings", **{f"s:{k}": v for k, v in cur.items()})
    assert st == 303, b[:500]


def load_demo(s):
    from driftwatch import demo
    created, otps = demo.load(s.db, s.cfg)
    return created, otps


def crawl(client, start, limit=300, skip=("/logout",)):
    """GET every same-site link reachable from start; return {path: status}."""
    seen, todo, out = set(), [start], {}
    while todo and len(out) < limit:
        p = todo.pop()
        if p in seen:
            continue
        seen.add(p)
        st, h, b = client.get(p)
        out[p] = st
        if st == 200:
            for href in re.findall(r'href="(/[^"#]*)"', b):
                href = href.replace("&amp;", "&")
                if href not in seen and not any(href.startswith(x) for x in skip) and not href.startswith("/static") and not re.search(r"/(snapshots|exports)/\d+", href) and "page=" not in href:
                    todo.append(href)
    return out
