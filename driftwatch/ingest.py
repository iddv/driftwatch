"""Fetch a source, store the snapshot and record changes."""
import json
import re
from datetime import timedelta

from . import fetcher, parsing, util
from .db import CATEGORIES


class Outcome:
    def __init__(self, result, detail="", new=0, snapshot_id=None, http_status=None, failure=False):
        self.result, self.detail, self.new = result, detail, new
        self.snapshot_id, self.http_status, self.failure = snapshot_id, http_status, failure


# ---------------------------------------------------------------- suggestions
def keyword_rules(db):
    return [(r["category"], r["keyword"]) for r in db.q("SELECT category,keyword FROM keyword_rules ORDER BY ord,id")]


def _kw_match(kw: str, text: str) -> bool:
    kw = kw.lower().strip()
    if not kw:
        return False
    if len(kw) <= 4 and kw.isalnum():  # short tokens (CVE, EOL) must be whole words
        return re.search(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", text) is not None
    return kw in text


def suggest(rules, title, text):
    hay = f"{title or ''}\n{text or ''}".lower()
    for cat, kw in rules:
        if _kw_match(kw, hay):
            return cat
    return "other"


# ---------------------------------------------------------------- locking
def acquire_lock(db, cfg, source_id) -> bool:
    now = util.now()
    cutoff = util.iso(now - timedelta(seconds=cfg.stale_lock_seconds))
    cur = db.x("UPDATE sources SET lock_at=? WHERE id=? AND (lock_at IS NULL OR lock_at < ?)",
               (util.iso(now), source_id, cutoff))
    return cur.rowcount == 1


def release_lock(db, source_id):
    db.x("UPDATE sources SET lock_at=NULL WHERE id=?", (source_id,))


# ---------------------------------------------------------------- entry creation
def _add_entry(db, rules, settings, src, snap_id, now_s, *, key, text_hash, kind, backfill, title, published, link,
               text_after, text_before=None, edit_of=None):
    cat = suggest(rules, title, f"{text_before or ''}\n{text_after or ''}")
    status, category, impact, rev_by, rev_at = "unreviewed", None, None, None, None
    if settings["triage.suggestions"] == "auto_apply" and cat != "other":
        status, category, impact, rev_by, rev_at = "reviewed", cat, "low", "system", now_s
    pub_s = util.iso(published) if published else None
    cur = db.x(
        """INSERT OR IGNORE INTO entries(source_id,vendor_id,snapshot_id,dedup_key,text_hash,kind,backfill,title,
           published_at,link,text_after,text_before,detected_at,eff_at,edit_of,suggested_category,status,category,
           impact,reviewed_by,reviewed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (src["id"], src["vendor_id"], snap_id, key, text_hash, kind, int(backfill), title, pub_s, link, text_after,
         text_before, now_s, pub_s or now_s, edit_of, cat, status, category, impact, rev_by, rev_at))
    if cur.rowcount != 1:
        return False
    eid = cur.lastrowid
    db.x("INSERT INTO entry_history(entry_id,ts,username,action,detail) VALUES(?,?,?,?,?)",
         (eid, now_s, "system", "detected", json.dumps({"suggested": cat, "kind": kind})))
    if status == "reviewed":
        db.x("INSERT INTO entry_history(entry_id,ts,username,action,detail) VALUES(?,?,?,?,?)",
             (eid, now_s, "system", "auto-applied", json.dumps({"category": cat, "impact": "low"})))
    return True


def effective_type(src, body, ctype):
    if src["type"] != "auto":
        return src["type"]
    t = parsing.sniff_type(body, ctype)
    return t if t in ("rss", "atom", "jsonfeed", "html") else "html"


def process_body(db, cfg, src, body: bytes, http_status, ctype, fetched_at=None) -> Outcome:
    """Store snapshot + entries for a fetched body in one transaction."""
    fetched_at = fetched_at or util.now()
    now_s = util.iso(fetched_at)
    sha = util.sha256(body)
    settings = db.all_settings()
    with db.tx():
        last = db.one("SELECT id,sha256,parse_ok,extract,selector FROM snapshots WHERE source_id=? ORDER BY id DESC LIMIT 1",
                      (src["id"],))
        if last and last["sha256"] == sha:
            if last["parse_ok"]:
                return Outcome("no change", "content hash unchanged", 0, last["id"], http_status)
            return Outcome("parse error", "unchanged body still cannot be parsed (raw body kept in snapshot "
                           f"#{last['id']})", 0, last["id"], http_status, failure=True)
        stype = effective_type(src, body, ctype)
        items, blocks, warn = None, None, ""
        parse_err = None
        try:
            if stype == "html":
                text = body.decode("utf-8", errors="replace")
                blocks, matched = parsing.html_extract(text, src["selector"])
                if matched is False:
                    warn = "selector matched nothing; used the full page"
            else:
                items = parsing.parse_feed(stype, body)
        except parsing.ParseError as exc:
            parse_err = str(exc)
        snap = db.x(
            "INSERT INTO snapshots(source_id,fetched_at,http_status,sha256,content_type,size,body,parse_ok,selector,extract)"
            " VALUES(?,?,?,?,?,?,?,?,?,?)",
            (src["id"], now_s, http_status, sha, ctype, len(body), body, 0 if parse_err else 1,
             src["selector"] if stype == "html" else None, json.dumps(blocks) if blocks is not None else None))
        sid = snap.lastrowid
        if parse_err:
            return Outcome("parse error", parse_err, 0, sid, http_status, failure=True)
        rules = keyword_rules(db)
        new = 0
        baseline = not src["baseline_done"]
        if items is not None:
            for it in items:
                key = it.key
                th = util.sha256(f"{it.title}\n{it.text}")
                existing = db.q("SELECT id,text_hash FROM entries WHERE source_id=? AND dedup_key=? ORDER BY id DESC",
                                (src["id"], key))
                if any(r["text_hash"] == th for r in existing):
                    continue
                kind = "edited" if existing else "item"
                if _add_entry(db, rules, settings, src, sid, now_s, key=key, text_hash=th, kind=kind,
                              backfill=baseline, title=it.title or (it.text[:80] if it.text else key),
                              published=it.published, link=it.link, text_after=it.text,
                              edit_of=existing[0]["id"] if existing else None):
                    new += 1
            detail = f"{len(items)} items in feed" + (" (baseline import)" if baseline else "")
        else:
            prev = None
            if last is not None:
                p = db.one("SELECT id,extract,selector FROM snapshots WHERE source_id=? AND parse_ok=1 AND id<? "
                           "AND extract IS NOT NULL ORDER BY id DESC LIMIT 1", (src["id"], sid))
                prev = p
            if prev is None or baseline or (prev["selector"] or "") != (src["selector"] or ""):
                detail = "baseline snapshot stored" if prev is None or baseline else "selector changed: new baseline stored"
            else:
                changes = parsing.diff_blocks(json.loads(prev["extract"]), blocks, settings_noise(settings))
                for ch in changes:
                    label = {"added": "Added", "removed": "Removed", "modified": "Modified"}[ch["kind"]]
                    basis = ch["after"] or ch["before"]
                    key = util.sha256(f"{sha}|{ch['kind']}|{ch['before']}|{ch['after']}")
                    if _add_entry(db, rules, settings, src, sid, now_s, key=key, text_hash=key, kind=ch["kind"],
                                  backfill=False, title=f"{label}: {basis[:90]}", published=None, link=src["url"],
                                  text_after=ch["after"], text_before=ch["before"]):
                        new += 1
                detail = f"{len(blocks)} blocks, {len(changes)} changed"
        if warn:
            detail += f"; {warn}"
        db.x("UPDATE sources SET baseline_done=1 WHERE id=?", (src["id"],))
        return Outcome("baseline" if baseline else ("ok" if new else "no new entries"), detail, new, sid, http_status)


def settings_noise(settings):
    return int(settings["diff.noise_chars"])


# ---------------------------------------------------------------- orchestration
def run_fetch(db, cfg, source_id, force_lock=False) -> Outcome:
    """Fetch one source now. Returns Outcome; result 'already fetching' when another fetch holds the lock."""
    if not acquire_lock(db, cfg, source_id):
        return Outcome("already fetching", "another fetch of this source is running")
    try:
        src = db.one("SELECT * FROM sources WHERE id=?", (source_id,))
        out = _fetch_and_process(db, cfg, src)
    except Exception as exc:  # never lose the lock on unexpected errors
        out = Outcome("error", f"internal error: {exc}", failure=True)
    finally:
        release_lock(db, source_id)
    _record(db, source_id, out)
    return out


def _fetch_and_process(db, cfg, src) -> Outcome:
    url, headers = fetcher.request_for_source(src["type"], src["url"], cfg)
    if db.setting("fetch.robots_txt") == "respect" and not fetcher.robots_allowed(url, cfg, loopback_ok=True):
        return Outcome("blocked by robots.txt", f"{url} is disallowed for {fetcher.USER_AGENT}", failure=True)
    try:
        resp = fetcher.fetch(url, cfg, headers, loopback_ok=True)
    except fetcher.FetchError as exc:
        return Outcome("error", exc.reason, http_status=exc.http_status, failure=True)
    return process_body(db, cfg, src, resp.body, resp.status, resp.content_type)


def _record(db, source_id, out: Outcome):
    now_s = util.now_iso()
    threshold = db.int_setting("fetch.failure_threshold")
    with db.tx():
        src = db.one("SELECT failures,failing FROM sources WHERE id=?", (source_id,))
        if src is None:
            return
        db.x("INSERT INTO fetch_log(source_id,ts,result,detail,http_status,new_entries,snapshot_id) VALUES(?,?,?,?,?,?,?)",
             (source_id, now_s, out.result, out.detail, out.http_status, out.new, out.snapshot_id))
        if out.failure:
            failures = src["failures"] + 1
            immediate = out.result == "blocked by robots.txt" and db.setting("fetch.robots_block_fails_immediately") == "true"
            failing = 1 if (failures >= threshold or immediate) else src["failing"]
            db.x("UPDATE sources SET last_attempt_at=?,last_result=?,last_new=0,failures=?,failing=?,"
                 "version=version+1 WHERE id=?", (now_s, f"{out.result}: {out.detail}", failures, failing, source_id))
        else:
            db.x("UPDATE sources SET last_attempt_at=?,last_fetch_at=?,last_result=?,last_new=?,failures=0,failing=0 "
                 "WHERE id=?", (now_s, now_s, out.result, out.new, source_id))


# ---------------------------------------------------------------- test fetch (stores nothing)
def test_fetch(cfg, stype, url, selector=None, robots="ignore", loopback_ok=False):
    """Return dict(ok, error, type, url, count, titles, warnings)."""
    res = {"ok": False, "error": None, "type": stype, "url": url, "count": 0, "titles": [], "warnings": []}
    err = fetcher.check_source_url(stype, url)
    if err:
        res["error"] = err
        return res
    req_url, headers = fetcher.request_for_source(stype, url, cfg)
    try:
        if robots == "respect" and not fetcher.robots_allowed(req_url, cfg, loopback_ok):
            res["error"] = "blocked by robots.txt"
            return res
        resp = fetcher.fetch(req_url, cfg, headers, loopback_ok=loopback_ok)
    except fetcher.FetchError as exc:
        res["error"] = exc.reason
        return res
    kind = stype
    if stype == "auto":
        kind, feed_url = fetcher.detect_type(resp)
        if feed_url:
            res["url"] = feed_url
            res["warnings"].append(f"Feed autodiscovered at {feed_url}")
            try:
                resp = fetcher.fetch(feed_url, cfg, loopback_ok=loopback_ok)
            except fetcher.FetchError as exc:
                res["error"] = f"autodiscovered feed failed: {exc.reason}"
                return res
        if kind is None:
            res["error"] = "could not detect the source type from the response"
            return res
    res["type"] = kind
    try:
        if kind == "html":
            blocks, matched = parsing.html_extract(resp.body.decode("utf-8", errors="replace"), selector)
            if matched is False:
                res["warnings"].append("Selector matched nothing; the full page body would be used.")
            res["count"] = len(blocks)
            res["titles"] = [b[:160] for b in blocks[:5]]
        else:
            items = parsing.parse_feed(kind, resp.body)
            res["count"] = len(items)
            items = sorted(items, key=lambda i: i.published.timestamp() if i.published else 0, reverse=True)
            res["titles"] = [(i.title or i.text[:80] or i.key)[:160] for i in items[:5]]
    except parsing.ParseError as exc:
        res["error"] = f"parse error: {exc}"
        return res
    res["ok"] = True
    return res
