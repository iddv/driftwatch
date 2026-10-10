"""HTTP server, dispatch, security headers, static and fixture routes."""
import errno
import hmac
import sys
import threading
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, quote, urlencode

from . import auth, fetcher, ui
from .router import ROUTES, Req, Resp, page, redirect, not_allowed, route
from . import v_auth, v_vendors, v_triage, v_reports, v_admin  # noqa: F401  (register routes)

MAX_BODY = 2 * 1024 * 1024
IDLE_TIMEOUT = 15  # seconds a client may stall before its connection is closed
MAX_CONNECTIONS = 200
CSP = "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"


class App:
    def __init__(self, db, cfg, scheduler=None):
        self.db, self.cfg, self.scheduler = db, cfg, scheduler


@route("GET", "/static/style.css", role=None)
def _css(req):
    return Resp(ui.CSS, ctype="text/css; charset=utf-8").header("Cache-Control", "max-age=300")


@route("GET", "/static/app.js", role=None)
def _js(req):
    return Resp(ui.JS, ctype="application/javascript; charset=utf-8").header("Cache-Control", "max-age=300")


@route("GET", "/health", role=None)
def _health(req):
    try:
        req.db.val("SELECT 1 FROM sqlite_master LIMIT 1")
    except Exception:
        return Resp("unavailable", 503, "text/plain")
    return Resp("ok", 200, "text/plain")


@route("GET", r"/_fixtures/([\w.-]+)", role=None)
def _fixture(req, name):
    """Bundled demo fixtures; only reachable by Driftwatch's own fetcher (secret header)."""
    sent = req.headers.get("X-Driftwatch-Fixture", "")
    if not hmac.compare_digest(sent, fetcher.fixture_token(req.cfg.session_secret)):
        return Resp("Not found", 404, "text/plain")
    p = Path(req.cfg.data_dir) / "fixtures" / name
    if not p.is_file():
        return Resp("Not found", 404, "text/plain")
    ctype = {".xml": "application/xml", ".json": "application/json", ".html": "text/html"}.get(p.suffix, "text/plain")
    return Resp(p.read_bytes(), 200, ctype)


def _find_route(method, path):
    allowed = False
    for m, rx, fn, role in ROUTES:
        mt = rx.match(path)
        if mt:
            if m == method or (method == "HEAD" and m == "GET"):
                return fn, role, mt.groups()
            allowed = True
    return (None, None, allowed)


def dispatch(app, method, path, query, form, cookies, headers) -> Resp:
    req = Req(app, method, path, query, form, cookies, headers)
    fn, role, groups = _find_route(method, path)
    if fn is None:
        resp = Resp("Method not allowed", 405, "text/plain") if groups else None
        if resp is None:
            req.user = req.session = None
            tok = cookies.get("dw_sess")
            u, s = auth.lookup_session(app.db, tok)
            req.user, req.session = u, s
            return page(req, "Not found", '<h1>Page not found</h1><p><a href="/vendors">Back to Vendors</a></p>', 404,
                        nav=bool(u))
        return resp
    tok = cookies.get("dw_sess")
    req.token = tok
    req.user, req.session = auth.lookup_session(app.db, tok)
    if role is not None:
        if not auth.admin_exists(app.db):
            return redirect(req, "/setup")
        if req.user is None:
            nxt = path + ("?" + urlencode(query, doseq=True) if query else "")
            return redirect(req, "/login?next=" + quote(nxt))
        if req.user["must_change"] and path not in ("/profile/password", "/logout"):
            return redirect(req, "/profile/password", "info", "You must change your one-time password before continuing.")
        if auth.RANK[req.user["role"]] < auth.RANK[role]:
            return not_allowed(req)
    if method == "POST" and not req.csrf_ok():
        return page(req, "Invalid request", "<h1>Invalid or expired form</h1><p>Reload the page and try again.</p>", 400,
                    nav=bool(req.user))
    resp = fn(req, *groups)
    if req.new_anon:
        resp.cookies.append(f"dw_anon={req.new_anon}; Path=/; HttpOnly; SameSite=Lax")
    return resp


class Handler(BaseHTTPRequestHandler):
    server_version = "Driftwatch"
    protocol_version = "HTTP/1.1"
    timeout = IDLE_TIMEOUT

    def log_message(self, fmt, *args):
        if getattr(self.server, "quiet", False):
            return
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _handle(self, method):
        try:
            parts = urlsplit(self.path)
            query = parse_qs(parts.query, keep_blank_values=True)
            form = {}
            if method == "POST":
                try:
                    n = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    n = -1
                if n < 0:
                    self.close_connection = True
                    return self._send(Resp("Bad Content-Length", 400, "text/plain"), method)
                if n > MAX_BODY:
                    self.close_connection = True
                    return self._send(Resp("Request too large", 413, "text/plain"), method)
                raw = self.rfile.read(n).decode("utf-8", errors="replace")
                form = parse_qs(raw, keep_blank_values=True)
            cookies = {k: m.value for k, m in SimpleCookie(self.headers.get("Cookie", "")).items()}
            hdrs = {k: v for k, v in self.headers.items()}
            resp = dispatch(self.server.app, method, parts.path, query, form, cookies, hdrs)
        except Exception:
            traceback.print_exc()
            resp = Resp("<h1>Something went wrong</h1><p>The error was logged.</p>", 500)
        finally:
            try:
                self.server.app.db.close()  # one connection per request thread
            except Exception:
                pass
        self._send(resp, method)

    def _send(self, resp: Resp, method):
        body = resp.body if method != "HEAD" else b""
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.ctype)
        self.send_header("Content-Length", str(len(resp.body)))
        self.send_header("Content-Security-Policy", CSP)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        if not any(k.lower() == "cache-control" for k, _ in resp.headers):
            self.send_header("Cache-Control", "no-store")
        for k, v in resp.headers:
            self.send_header(k, v)
        for c in resp.cookies:
            self.send_header("Set-Cookie", c)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._handle("GET")

    def do_HEAD(self):
        self._handle("HEAD")

    def do_POST(self):
        self._handle("POST")


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, *a, **kw):
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
        super().__init__(*a, **kw)

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            self.shutdown_request(request)
            return
        super().process_request(request, client_address)

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()


def make_server(app, cfg, quiet=False):
    try:
        srv = Server((cfg.host, cfg.port), Handler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            raise SystemExit(f"Port {cfg.port} is already in use. Set DRIFTWATCH_LISTEN (for example "
                             f"DRIFTWATCH_LISTEN=127.0.0.1:8081) to choose another address.")
        raise SystemExit(f"Cannot listen on {cfg.listen}: {exc.strerror}. Check DRIFTWATCH_LISTEN.")
    srv.app = app
    srv.quiet = quiet
    return srv
