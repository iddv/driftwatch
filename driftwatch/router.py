"""Request/response objects and the route table shared by all views."""
import json
import re
from urllib.parse import quote

from . import auth, ui, util
from .util import esc

ROUTES = []


def route(method, pattern, role="viewer"):
    """role: None = public, otherwise the minimum role."""
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn, role))
        return fn
    return deco


class Resp:
    def __init__(self, body=b"", status=200, ctype="text/html; charset=utf-8", headers=None):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.status, self.ctype = status, ctype
        self.headers = list(headers or [])
        self.cookies = []

    def header(self, k, v):
        self.headers.append((k, v))
        return self


class Req:
    def __init__(self, app, method, path, query, form, cookies, headers):
        self.app, self.method, self.path = app, method, path
        self.query, self.form, self.cookies, self.headers = query, form, cookies, headers
        self.user = self.session = None
        self.token = None
        self.anon = cookies.get("dw_anon")
        self.new_anon = None
        self.pending_flash = []

    @property
    def db(self):
        return self.app.db

    @property
    def cfg(self):
        return self.app.cfg

    def get(self, name, default=""):
        src = self.form if self.method == "POST" else self.query
        v = src.get(name)
        return (v[0] if v else default).strip() if isinstance(default, str) else (v[0] if v else default)

    def raw(self, name, default=""):
        src = self.form if self.method == "POST" else self.query
        v = src.get(name)
        return v[0] if v else default

    def getlist(self, name):
        src = self.form if self.method == "POST" else self.query
        return [x for x in src.get(name, []) if x != ""]

    def int(self, name, default=None):
        try:
            n = int(self.get(name))
        except ValueError:
            return default
        return n if -2**62 < n < 2**62 else default  # beyond SQLite's INTEGER range: treat as invalid

    def csrf_value(self):
        if self.session is not None:
            return auth.csrf_token(self.cfg.session_secret, self.session["token_hash"])
        if not self.anon:
            import secrets
            self.anon = self.new_anon = secrets.token_urlsafe(16)
        return auth.csrf_token(self.cfg.session_secret, "anon:" + self.anon)

    def csrf(self):
        return f'<input type="hidden" name="_csrf" value="{self.csrf_value()}">'

    def csrf_ok(self):
        sent = (self.form.get("_csrf") or [""])[0]
        if self.session is not None:
            want = auth.csrf_token(self.cfg.session_secret, self.session["token_hash"])
        elif self.anon:
            want = auth.csrf_token(self.cfg.session_secret, "anon:" + self.anon)
        else:
            return False
        import hmac
        return hmac.compare_digest(sent, want)

    def flash(self, kind, msg):
        if self.session is not None:
            cur = json.loads(self.session["flash"] or "[]")
            cur.append([kind, msg])
            self.db.x("UPDATE sessions SET flash=? WHERE token_hash=?", (json.dumps(cur), self.session["token_hash"]))
            self.session = dict(self.session)
            self.session["flash"] = json.dumps(cur)
        else:
            self.pending_flash.append((kind, msg))

    def take_flashes(self):
        out = list(self.pending_flash)
        if self.session is not None and self.session["flash"]:
            out += [tuple(x) for x in json.loads(self.session["flash"])]
            self.db.x("UPDATE sessions SET flash=NULL WHERE token_hash=?", (self.session["token_hash"],))
            self.session = dict(self.session)
            self.session["flash"] = None
        return out

    def role_at_least(self, role):
        return self.user is not None and auth.RANK[self.user["role"]] >= auth.RANK[role]

    @property
    def can_edit(self):
        return self.role_at_least("analyst")

    @property
    def is_admin(self):
        return self.role_at_least("admin")


def page(req, title, body, status=200, nav=True):
    return Resp(ui.layout(title, body, req.user, req.take_flashes(), req.csrf_value() if req.session is not None else "", nav),
                status)


def redirect(req, url, kind=None, msg=None):
    if msg:
        req.flash(kind or "ok", msg)
    return Resp(b"", 303, headers=[("Location", url)])


def not_allowed(req):
    return page(req, "Not allowed", "<h1>Not allowed</h1><p>Your role does not permit this action.</p>"
                '<p><a href="/vendors">Back to Vendors</a></p>', 403)


def not_found(req, what="Page", back=("/vendors", "Vendors")):
    return page(req, "Not found", f"<h1>{esc(what)} not found</h1><p><a href=\"{back[0]}\">Back to {esc(back[1])}</a></p>", 404)


def download(data: bytes, filename: str, ctype="application/octet-stream"):
    r = Resp(data, 200, ctype)
    r.header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
    return r


def safe_next(url):
    return url if url and url.startswith("/") and not url.startswith("//") and "\\" not in url else "/vendors"


def conflict_message(db, row):
    who = row["updated_by"] or "another user"
    when = util.parse_dt(row["updated_at"])
    ts = when.strftime("%Y-%m-%d %H:%M UTC") if when else "just now"
    return f"Changed by {who} at {ts}, reload to see their version"
