import http.client
import re
import tempfile
import threading
import unittest
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlencode

from driftwatch import config, web
from driftwatch.db import Database


class Client:
    def __init__(self, port):
        self.port, self.cookies, self.csrf = port, {}, None

    def request(self, method, path, data=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        headers = {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}
        body = None
        if data is not None:
            body = urlencode(data, doseq=True)
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body, headers)
        r = conn.getresponse()
        raw = r.read()
        for h, v in r.getheaders():
            if h.lower() == "set-cookie":
                for k, m in SimpleCookie(v).items():
                    if m.value:
                        self.cookies[k] = m.value
                    else:
                        self.cookies.pop(k, None)
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


class AppCase(unittest.TestCase):
    """Starts a real Driftwatch server on an ephemeral port with a throw-away data directory."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cfg = config.load(env={})
        cfg.data_dir = Path(cls._tmp.name)
        cfg.port = 0
        cfg.fetch_timeout = 5
        config.prepare_data_dir(cfg)
        cls.db = Database(cfg.db_path)
        cls.db.migrate()
        cls.app = web.App(cls.db, cfg)
        cls.srv = web.make_server(cls.app, cfg, quiet=True)
        cfg.port = cls.srv.server_address[1]
        cls.cfg = cfg
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cfg.port
        cls.admin = Client(cls.port)
        tok = cls.admin.token("/setup")
        s, _, _ = cls.admin.request("POST", "/setup", {"_csrf": tok, "username": "root", "password": "a-long-password-1",
                                                       "password2": "a-long-password-1"})
        assert s == 303, s
        cls.admin.csrf = cls.admin.token("/profile")

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.db.close()
        cls._tmp.cleanup()

    def allow_loopback(self):
        """Let this test's local listeners be fetched (the operator allow-list)."""
        self.cfg.fetch_allow_hosts = "127.0.0.1"
        self.addCleanup(setattr, self.cfg, "fetch_allow_hosts", "")

    def fixture(self, name, content):
        (self.cfg.data_dir / "fixtures" / name).write_bytes(content if isinstance(content, bytes) else content.encode())

    def fixture_url(self, name):
        return f"{self.cfg.base_url}/_fixtures/{name}"

    def make_user(self, username, role):
        s, h, b = self.admin.post("/users/new", username=username, role=role)
        self.assertEqual(s, 200, b[:300])
        otp = re.search(r'<code id="otp">([^<]+)</code>', b).group(1)
        c = Client(self.port)
        self.assertEqual(c.login(username, otp)[0], 303)
        newpw = "new-password-for-" + username
        s, h, b = c.post("/profile/password", current=otp, new=newpw, new2=newpw)
        self.assertEqual(s, 303, b[:400])
        c.password = newpw
        return c

    def add_vendor(self, name, category="database", client=None):
        s, h, b = (client or self.admin).post("/vendors/new", name=name, category=category)
        self.assertEqual(s, 303, b[:500])
        return int(h["Location"].rsplit("/", 1)[1])

    def add_source(self, vid, name, stype, url=None, **kw):
        s, h, b = self.admin.post(f"/vendors/{vid}/sources/new", url=url or self.fixture_url(name), type=stype,
                                  interval_min="360", **kw)
        self.assertEqual(s, 303, b[:800])
        return int(h["Location"].rsplit("/", 1)[1])


def rss(items):
    body = "".join(f"<item><title>{t}</title><guid>{g}</guid><pubDate>{d}</pubDate><description>{x}</description></item>"
                   for g, t, d, x in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>{body}</channel></rss>'
