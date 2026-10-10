"""Outbound HTTP: limits, redirects, proxy, robots.txt, type detection."""
import hmac
import hashlib
import http.client
import ipaddress
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit, urljoin

from urllib.robotparser import RobotFileParser

from . import __version__, parsing

USER_AGENT = f"Driftwatch/{__version__} (+self-hosted)"
FIXTURE_PREFIX = "/_fixtures/"


class FetchError(Exception):
    def __init__(self, reason, http_status=None, kind="error"):
        super().__init__(reason)
        self.reason, self.http_status, self.kind = reason, http_status, kind


@dataclass
class Response:
    status: int
    body: bytes
    content_type: str
    url: str


def fixture_token(secret: str) -> str:
    return hmac.new(secret.encode(), b"driftwatch-fixture", hashlib.sha256).hexdigest()


def validate_url(url: str):
    """Return an error string, or None when url is a usable http(s) URL."""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return "Enter a valid URL"
    if p.scheme not in ("http", "https"):
        return "Only http and https URLs are allowed"
    if not p.hostname:
        return "Enter a valid URL"
    try:
        p.port
    except ValueError:
        return "Enter a valid URL"
    return None


BLOCKED = "refused: the address is loopback, link-local or on a private network"


def _is_fixture_url(url, cfg):
    p = urlsplit(url)
    return p.path.startswith(FIXTURE_PREFIX) and _is_loopback(p.hostname) and (p.port or 80) == cfg.port


def _allowed_by_operator(host, ip, cfg):
    for item in (x.strip() for x in cfg.fetch_allow_hosts.split(",")):
        if not item:
            continue
        if item.lower() == (host or "").lower():
            return True
        try:
            if ip in ipaddress.ip_network(item, strict=False):
                return True
        except ValueError:
            pass
    return False


def _check_ip(host, ip_text, cfg, loopback_ok=False):
    ip = ipaddress.ip_address(ip_text.split("%")[0])
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    if ip.is_global or (loopback_ok and ip.is_loopback) or _allowed_by_operator(host, ip, cfg):
        return
    raise FetchError(BLOCKED)


def check_host(host, port, cfg, loopback_ok=False):
    """Resolve host and refuse non-public addresses (unless the operator allow-listed them)."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError(f"DNS lookup failed: {exc.strerror or exc}")
    for info in infos:
        _check_ip(host, info[4][0], cfg, loopback_ok)


class _State:
    def __init__(self, fixture_ok, loopback_ok=False):
        self.fixture_ok, self.loopback_ok = fixture_ok, loopback_ok


def _guarded(base, cfg, state, check_peer):
    class Conn(base):
        def connect(self):
            if not (state.fixture_ok and _is_loopback(self.host) and self.port == cfg.port) and check_peer:
                check_host(self.host, self.port, cfg, state.loopback_ok)
            super().connect()
            if check_peer and not (state.fixture_ok and _is_loopback(self.host) and self.port == cfg.port):
                try:
                    _check_ip(self.host, self.sock.getpeername()[0], cfg, state.loopback_ok)
                except FetchError:
                    self.close()
                    raise
    return Conn


def _http_handler(cls, base, cfg, state, check_peer):
    conn = _guarded(base, cfg, state, check_peer)

    class H(cls):
        def http_open(self, req):
            return self.do_open(conn, req)

        def https_open(self, req):
            return self.do_open(conn, req, context=self._context)
    return H


class _Redirects(urllib.request.HTTPRedirectHandler):
    max_redirections = 5
    state = None
    cfg = None

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme not in ("http", "https"):
            raise urllib.error.HTTPError(newurl, code, "redirect to a non-http(s) URL", headers, fp)
        self.state.fixture_ok = _is_fixture_url(urljoin(req.full_url, newurl), self.cfg)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _is_loopback(host):
    return host in ("localhost", "127.0.0.1", "::1") or (host or "").startswith("127.")


def fetch(url: str, cfg, headers=None, max_bytes=None, loopback_ok=False) -> Response:
    """loopback_ok: scheduled/saved-source fetches may reach this machine (private networks and cloud metadata
    stay refused); the interactive source test never may."""
    err = validate_url(url)
    if err:
        raise FetchError(err)
    host = urlsplit(url).hostname
    hdrs = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    if urlsplit(url).path.startswith(FIXTURE_PREFIX) and _is_loopback(host):
        hdrs["X-Driftwatch-Fixture"] = fixture_token(cfg.session_secret)
    hdrs.update(headers or {})
    state = _State(_is_fixture_url(url, cfg), loopback_ok)
    if not state.fixture_ok:
        check_host(host, urlsplit(url).port or (443 if url.lower().startswith("https") else 80), cfg, loopback_ok)
    handlers = [_Redirects()]
    handlers[0].max_redirections = cfg.fetch_max_redirects
    handlers[0].state, handlers[0].cfg = state, cfg
    proxied = bool(cfg.http_proxy) and not _is_loopback(host)
    if proxied:
        handlers.append(urllib.request.ProxyHandler({"http": cfg.http_proxy, "https": cfg.http_proxy}))
    else:
        handlers.append(urllib.request.ProxyHandler({}))
    handlers.append(_http_handler(urllib.request.HTTPHandler, http.client.HTTPConnection, cfg, state, not proxied)())
    handlers.append(_http_handler(urllib.request.HTTPSHandler, http.client.HTTPSConnection, cfg, state, not proxied)())
    opener = urllib.request.build_opener(*handlers)
    limit = max_bytes or cfg.fetch_max_bytes
    deadline = time.monotonic() + cfg.fetch_timeout
    try:
        with opener.open(urllib.request.Request(url, headers=hdrs), timeout=cfg.fetch_timeout) as resp:
            chunks, total = [], 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise FetchError(f"response larger than the {limit // 1024} KB limit", resp.status, "too large")
                if time.monotonic() > deadline:
                    raise FetchError(f"timed out after {cfg.fetch_timeout}s", resp.status, "timeout")
                chunks.append(chunk)
            return Response(resp.status, b"".join(chunks), resp.headers.get("Content-Type", ""), resp.geturl())
    except FetchError:
        raise
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            raise FetchError(f"too many redirects (limit {cfg.fetch_max_redirects})", exc.code)
        raise FetchError(f"HTTP {exc.code} {exc.reason}", exc.code)
    except urllib.error.URLError as exc:
        r = exc.reason
        if isinstance(r, socket.gaierror):
            raise FetchError(f"DNS lookup failed: {r.strerror or r}")
        if isinstance(r, (socket.timeout, TimeoutError)):
            raise FetchError(f"timed out after {cfg.fetch_timeout}s", kind="timeout")
        raise FetchError(f"connection failed: {r}")
    except (socket.timeout, TimeoutError):
        raise FetchError(f"timed out after {cfg.fetch_timeout}s", kind="timeout")
    except (OSError, ValueError) as exc:
        raise FetchError(f"request failed: {exc}")


# ---- robots.txt (cached for an hour per origin)
_robots_cache = {}


def robots_allowed(url: str, cfg, loopback_ok=False) -> bool:
    p = urlsplit(url)
    if p.path.startswith(FIXTURE_PREFIX) and _is_loopback(p.hostname):
        return True
    origin = f"{p.scheme}://{p.netloc}"
    hit = _robots_cache.get(origin)
    if hit and time.monotonic() - hit[0] < 3600:
        rp = hit[1]
    else:
        rp = RobotFileParser()
        try:
            r = fetch(origin + "/robots.txt", cfg, max_bytes=512 * 1024, loopback_ok=loopback_ok)
            rp.parse(r.body.decode("utf-8", errors="replace").splitlines())
        except FetchError:
            rp.parse([])  # missing/unreachable robots.txt: nothing is disallowed
        _robots_cache[origin] = (time.monotonic(), rp)
    return rp.can_fetch(USER_AGENT, url)


def clear_robots_cache():
    _robots_cache.clear()


# ---- source URL handling
_GH = re.compile(r"^([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)$")


def request_for_source(stype: str, url: str, cfg):
    """(url, headers) actually requested for a source."""
    if stype == "github":
        m = _GH.match(url.strip())
        if m:
            owner, repo = m.groups()
            if cfg.github_token:
                return (f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=100",
                        {"Authorization": f"Bearer {cfg.github_token}", "Accept": "application/vnd.github+json"})
            return f"https://github.com/{owner}/{repo}/releases.atom", {}
    return url.strip(), {}


def check_source_url(stype: str, url: str):
    if stype == "github" and _GH.match(url.strip()):
        return None
    return validate_url(url)


def detect_type(resp: Response):
    """Return (type, feed_url_or_None). type may be 'html' with a discovered feed link."""
    t = parsing.sniff_type(resp.body, resp.content_type)
    if t == "html":
        links = parsing.find_feed_links(resp.body.decode("utf-8", errors="replace"), resp.url)
        if links:
            return links[0][1], links[0][0]
    return t, None
