"""Demo data: 8 vendors, 16 sources, ~150 entries over 18 months, served from local fixture files."""
import json
import random
from datetime import timedelta
from xml.sax.saxutils import escape as xesc

from . import auth, ingest, util
from .db import CATEGORIES

VENDORS = [
    ("Pelican Postgres", "database", "https://pelican-postgres.example/", "managed Postgres", ["rss", "html"]),
    ("Northgate Identity", "identity", "https://northgate-identity.example/", "identity provider", ["atom", "github"]),
    ("Vaultline", "secrets", "https://vaultline.example/", "secrets manager", ["jsonfeed", "html"]),
    ("Cumulus Cloud", "cloud infrastructure", "https://cumulus-cloud.example/", "cloud platform", ["rss", "jsonfeed"]),
    ("Beacon Observability", "observability", "https://beacon-obs.example/", "monitoring service", ["atom", "html"]),
    ("Paystream", "payments", "https://paystream.example/", "payments API", ["rss", "github"]),
    ("Keystone Directory", "identity", "https://keystone-directory.example/", "directory service", ["atom", "html"]),
    ("Graphite DB", "database", "https://graphite-db.example/", "document database", ["jsonfeed", "github"]),
]

FEATURES = ["the v1 REST API", "legacy token format", "the dashboard export", "TLS 1.1 connections", "the batch endpoint",
            "password-based API access", "the classic console", "webhook retries", "the audit stream", "SDK v3",
            "the EU-West region", "cross-project sharing", "the Terraform provider 1.x", "anonymous read access"]

# (category-ish, title template, body template)
TEMPLATES = [
    ("dep", "Deprecation of {f}", "{f} is deprecated and will sunset on {d}. Please migrate before that date."),
    ("dep", "{f} reaches end of life", "Support for {f} will reach end of life in {d}. No further updates will be shipped."),
    ("rem", "Removed {f}", "As announced earlier, {f} has been removed. Requests that still use it will fail."),
    ("rem", "{f} discontinued", "We discontinued {f} for all new projects. Existing projects keep working until {d}."),
    ("brk", "Breaking change in {f}", "This release contains a breaking change to {f}. Responses are incompatible with earlier clients."),
    ("dflt", "{f}: new default behavior", "The default for {f} changed. New projects now require explicit opt-out; this is enabled by default."),
    ("dflt", "{f} now requires authentication", "{f} now requires a signed request. Unauthenticated calls are rejected."),
    ("scope", "Quota changes for {f}", "The free plan quota for {f} is reduced and the rate limit is lower. {f} is only available on paid plans after {d}."),
    ("scope", "{f} restricted to paid plans", "Access to {f} is restricted to team plans and above from {d}."),
    ("sec", "Security update: CVE-2026-{n}", "We patched a vulnerability (CVE-2026-{n}) in {f}. Customers should upgrade to the latest release."),
    ("sec", "Security hardening for {f}", "This release improves security of {f} with stricter validation of inputs."),
    ("new", "New: {f} improvements", "We added support for scheduled changes in {f}, with a refreshed dashboard view."),
    ("new", "Introducing regional replicas", "Customers can now add read replicas in three additional regions."),
    ("fix", "Fixed intermittent errors in {f}", "A bug that caused occasional timeouts in {f} has been corrected."),
    ("fix", "Improved performance of {f}", "Latency for {f} improved for large accounts."),
    ("oth", "Release notes {n}", "Maintenance release with documentation updates and internal improvements."),
    ("oth", "Status page moved", "The public status page now lives on a new address. Subscribe again to receive updates."),
]
WEIGHTS = {"dep": 3, "rem": 2, "brk": 2, "dflt": 3, "scope": 3, "sec": 2, "new": 3, "fix": 3, "oth": 2}

HTML_BASE_STATIC = ["Welcome to the changelog. This page lists notable changes for {v}.",
                    "Subscribe to the feed to be notified about new releases.",
                    "Contact support if you have questions about a release."]
HTML_EVENTS = [
    ("modify", "Connections per instance are capped at 100 for all plans.",
     "Connections per instance are limited to 50 on the standard plan; the quota for premium plans is unchanged."),
    ("modify", "TLS 1.0 and 1.1 are accepted for legacy clients.",
     "TLS 1.0 and 1.1 are no longer supported in any region. Clients must use TLS 1.2 or newer."),
    ("remove", "The v1 REST API is available at /api/v1 for all customers.", None),
    ("add", None, "The v1 REST API is deprecated and will sunset in six months. Migrate to v2 before then."),
    ("modify", "Audit logs are retained for 90 days.",
     "Audit logs are retained for 30 days by default; longer retention requires an add-on plan."),
    ("add", None, "Multi-region failover is generally available for all customers."),
    ("modify", "API keys do not expire.",
     "API keys now expire after 90 days. This is a breaking change for integrations that rotate keys manually."),
    ("add", None, "Security advisory: a vulnerability (CVE-2026-1182) affecting the admin console was patched in this release."),
    ("remove", "Self-service export of backups is available from the dashboard.", None),
    ("add", None, "The dashboard now includes a new usage view for the whole team."),
    ("modify", "Support responses are sent within 8 hours.", "Support responses are sent within 24 hours for standard plans."),
]


def _slug(s):
    return "".join(c if c.isalnum() else "-" for c in s.lower()).strip("-")


# ---------------------------------------------------------------- document builders
def _rss(v, items):
    body = "".join(
        f"<item><title>{xesc(i['title'])}</title><link>{xesc(i['link'])}</link><guid isPermaLink=\"false\">{xesc(i['guid'])}</guid>"
        f"<pubDate>{i['pub'].strftime('%a, %d %b %Y %H:%M:%S GMT')}</pubDate><description>{xesc('<p>' + xesc(i['text']) + '</p>')}</description></item>"
        for i in reversed(items))
    return (f'<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>{xesc(v)} release notes</title>'
            f'<link>https://example.invalid/</link><description>Changes</description>{body}</channel></rss>').encode()


def _atom(v, items):
    body = "".join(
        f"<entry><id>{xesc(i['guid'])}</id><title>{xesc(i['title'])}</title><link rel=\"alternate\" href=\"{xesc(i['link'])}\"/>"
        f"<published>{util.iso(i['pub'])}</published><updated>{util.iso(i['pub'])}</updated><content type=\"text\">{xesc(i['text'])}</content></entry>"
        for i in reversed(items))
    return (f'<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom"><title>{xesc(v)}</title>'
            f'<id>urn:demo:{xesc(_slug(v))}</id><updated>{util.now_iso()}</updated>{body}</feed>').encode()


def _jsonfeed(v, items):
    return json.dumps({"version": "https://jsonfeed.org/version/1.1", "title": f"{v} changelog", "items": [
        {"id": i["guid"], "url": i["link"], "title": i["title"], "content_text": i["text"], "date_published": util.iso(i["pub"])}
        for i in reversed(items)]}, indent=1).encode()


def _html(v, blocks):
    lis = "".join(f"<li>{xesc(b)}</li>" for b in blocks[:-3])
    paras = "".join(f"<p>{xesc(b)}</p>" for b in blocks[-3:])
    return (f"<!doctype html><html><head><title>{xesc(v)} changelog</title><script>var x=1;</script></head><body>"
            f"<nav><a href='/'>Home</a> <a href='/docs'>Docs</a></nav><div id='changelog'><h1>{xesc(v)} changelog</h1>"
            f"<ul>{lis}</ul>{paras}</div><footer>Copyright {xesc(v)}</footer></body></html>").encode()


BUILDERS = {"rss": (_rss, "xml", "application/rss+xml"), "atom": (_atom, "xml", "application/atom+xml"),
            "github": (_atom, "xml", "application/atom+xml"), "jsonfeed": (_jsonfeed, "json", "application/feed+json")}


# ---------------------------------------------------------------- loader
class DemoError(Exception):
    pass


def load(db, cfg, force_into_existing=False, seed=7):
    if db.val("SELECT COUNT(*) FROM vendors") and not force_into_existing:
        raise DemoError("This system already has vendors. Demo data is only loaded into an empty system; "
                        "rerun with --force-into-existing to add it anyway.")
    names = [v[0] for v in VENDORS]
    clash = [r[0] for r in db.q(f"SELECT name FROM vendors WHERE name IN ({','.join('?' * len(names))})", names)]
    if clash:
        raise DemoError(f"Vendors with these names already exist: {', '.join(clash)}")
    rnd = random.Random(seed)
    now = util.now()
    fixdir = cfg.data_dir / "fixtures"
    fixdir.mkdir(parents=True, exist_ok=True)
    otps = {}
    with db.tx():
        created = {"vendors": 0, "sources": 0, "entries": 0}
        ts = util.iso(now)
        for vi, (name, cat, home, kind_word, types) in enumerate(VENDORS):
            renewal = (now + timedelta(days=60 + vi * 37)).date().isoformat()
            vid = db.x("INSERT INTO vendors(name,category,homepage,renewal_date,notes,created_at,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                       (name, cat, home, renewal, f"Demo vendor: {kind_word}.", ts, "demo", ts)).lastrowid
            created["vendors"] += 1
            for si, stype in enumerate(types):
                fname = f"demo-{_slug(name)}-{si + 1}.{'html' if stype == 'html' else BUILDERS[stype][1]}"
                url = f"{cfg.base_url}/_fixtures/{fname}"
                selector = "#changelog" if stype == "html" else None
                interval = [360, 720, 1440][(vi + si) % 3] * 60
                sid = db.x("INSERT INTO sources(vendor_id,url,type,selector,interval_s,created_at,updated_by,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                           (vid, url, stype, selector, interval, ts, "demo", ts)).lastrowid
                created["sources"] += 1
                steps = (_html_steps if stype == "html" else _feed_steps)(rnd, name, stype, now, fname)
                final = None
                for fetched_at, body, ctype in steps:
                    src = db.one("SELECT * FROM sources WHERE id=?", (sid,))
                    out = ingest.process_body(db, cfg, src, body, 200, ctype, fetched_at)
                    created["entries"] += out.new
                    db.x("INSERT INTO fetch_log(source_id,ts,result,detail,http_status,new_entries,snapshot_id) VALUES(?,?,?,?,?,?,?)",
                         (sid, util.iso(fetched_at), out.result, out.detail, 200, out.new, out.snapshot_id))
                    final = (fetched_at, body, out)
                (fixdir / fname).write_bytes(final[1])
                db.x("UPDATE sources SET last_attempt_at=?,last_fetch_at=?,last_result=?,last_new=? WHERE id=?",
                     (ts, util.iso(final[0]), final[2].result, final[2].new, sid))
        _triage_some(db, rnd, now)
        analyst_id = None
        for uname, role in (("demo-analyst", "analyst"), ("demo-viewer", "viewer")):
            if db.val("SELECT 1 FROM users WHERE username=?", (uname,)):
                continue
            otp = auth.one_time_password(db)
            auth.create_user(db, uname, role, otp, must_change=True)
            otps[uname] = otp
        db.audit("cli", "demo.load", created)
    return created, otps


def _triage_some(db, rnd, now):
    rows = db.q("SELECT id,detected_at,suggested_category FROM entries WHERE status='unreviewed' ORDER BY id")
    behavior = ["breaking change", "removal", "deprecation", "default change", "scope narrowing", "security"]
    for r in rows:
        roll = rnd.random()
        if roll < 0.35:
            continue
        who = "demo-analyst"
        det = util.parse_dt(r["detected_at"])
        at = min(now, det + timedelta(hours=rnd.randint(2, 200)))
        when = util.iso(at)
        if roll < 0.50:
            reason = rnd.choice(["Marketing post", "Typo fix only", "Not relevant to our usage", None])
            db.x("UPDATE entries SET status='dismissed',dismiss_reason=?,reviewed_by=?,reviewed_at=?,version=version+1,updated_by=?,updated_at=? WHERE id=?",
                 (reason, who, when, who, when, r["id"]))
            db.x("INSERT INTO entry_history(entry_id,ts,username,action,detail) VALUES(?,?,?,?,?)",
                 (r["id"], when, who, "dismissed", json.dumps({"reason": reason})))
            continue
        cat = r["suggested_category"] if rnd.random() < 0.8 else rnd.choice(behavior + ["other", "new capability"])
        impact = rnd.choices(["low", "medium", "high"], [4, 4, 2])[0]
        note = "Affects our integration; plan a migration." if impact == "high" else (rnd.choice(["", "Checked docs.", ""]) or None)
        affects = 1 if (impact == "high" or rnd.random() < 0.1) else 0
        db.x("UPDATE entries SET status='reviewed',category=?,impact=?,note=?,affects_us=?,reviewed_by=?,reviewed_at=?,"
             "version=version+1,updated_by=?,updated_at=? WHERE id=?", (cat, impact, note, affects, who, when, who, when, r["id"]))
        db.x("INSERT INTO entry_history(entry_id,ts,username,action,detail) VALUES(?,?,?,?,?)",
             (r["id"], when, who, "reviewed", json.dumps({"category": cat, "impact": impact})))


def _feed_steps(rnd, vendor, stype, now, fname):
    builder, _, ctype = BUILDERS[stype]
    n = rnd.randint(9, 12)
    items = []
    start = now - timedelta(days=548)
    for k in range(n):
        tag = rnd.choices(list(WEIGHTS), list(WEIGHTS.values()))[0]
        tpl = rnd.choice([t for t in TEMPLATES if t[0] == tag])
        f = rnd.choice(FEATURES)
        d = (now + timedelta(days=rnd.randint(-100, 200))).strftime("%B %Y")
        num = rnd.randint(1000, 9999)
        pub = start + timedelta(days=rnd.randint(0, 540), hours=rnd.randint(0, 23), minutes=rnd.randint(0, 59))
        pub = min(pub, now - timedelta(days=1)).replace(microsecond=0)
        items.append({"guid": f"{_slug(vendor)}-{k + 1}-{num}", "title": f"{vendor}: " + tpl[1].format(f=f, d=d, n=num),
                      "text": tpl[2].format(f=f, d=d, n=num), "pub": pub,
                      "link": f"https://example.invalid/{_slug(vendor)}/changes/{k + 1}"})
    items.sort(key=lambda i: i["pub"])
    base_time = now - timedelta(days=420)
    early = [i for i in items if i["pub"] <= base_time] or items[:2]
    later = [i for i in items if i not in early]
    steps = [(base_time, builder(vendor, [dict(i) for i in early]), ctype)]
    current = [dict(i) for i in early]
    for i in later:
        current.append(dict(i))
        steps.append((min(now - timedelta(hours=3), i["pub"] + timedelta(hours=3)), builder(vendor, [dict(x) for x in current]), ctype))
    # one source in three gets an edited item: same guid, changed text
    if rnd.random() < 0.4 and len(current) > 3:
        victim = current[len(current) // 2]
        victim["text"] += " Update: the date was moved by one quarter after customer feedback."
        steps.append((now - timedelta(days=2), builder(vendor, [dict(x) for x in current]), ctype))
    return steps


def _html_steps(rnd, vendor, stype, now, fname):
    events = rnd.sample(HTML_EVENTS, 7)
    blocks = [t.format(v=vendor) for t in HTML_BASE_STATIC]
    for kind, before, after in HTML_EVENTS:
        if before and (kind != "modify" or True) and any(e[1] == before for e in events):
            blocks.insert(0, before)
    ctype = "text/html"
    base_time = now - timedelta(days=430)
    steps = [(base_time, _html(vendor, blocks), ctype)]
    span = 400
    for idx, (kind, before, after) in enumerate(events):
        at = base_time + timedelta(days=int((idx + 1) * span / (len(events) + 1)) + rnd.randint(-5, 5), hours=rnd.randint(0, 20))
        at = min(at, now - timedelta(days=3))
        if kind == "modify":
            blocks = [after if b == before else b for b in blocks]
        elif kind == "remove":
            blocks = [b for b in blocks if b != before]
        else:
            blocks.insert(0, after)
        steps.append((at, _html(vendor, blocks), ctype))
    return steps
