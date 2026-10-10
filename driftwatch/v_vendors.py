"""Vendor and source management views (F2, F3)."""
import json
from datetime import date

from . import fetcher, ingest, parsing, ui, util
from .db import VENDOR_CATEGORIES, SOURCE_TYPES, SOURCE_TYPE_LABELS
from .router import route, page, redirect, not_found, not_allowed, conflict_message, Resp, download
from .util import esc


def _vendor(req, vid):
    return req.db.one("SELECT * FROM vendors WHERE id=?", (vid,))


def _source(req, sid):
    return req.db.one("SELECT * FROM sources WHERE id=?", (sid,))


# ------------------------------------------------------------------ vendor list
@route("GET", "/vendors")
def vendors(req):
    archived = req.get("archived") == "1"
    cat = req.get("category")
    sql = ("SELECT v.*, (SELECT COUNT(*) FROM sources s WHERE s.vendor_id=v.id) AS n_sources,"
           " (SELECT COUNT(*) FROM sources s WHERE s.vendor_id=v.id AND s.failing=1) AS n_failing,"
           " (SELECT COUNT(*) FROM entries e WHERE e.vendor_id=v.id AND e.status='unreviewed') AS n_unrev,"
           " (SELECT COUNT(*) FROM entries e WHERE e.vendor_id=v.id) AS n_entries"
           " FROM vendors v WHERE v.archived=?")
    args = [1 if archived else 0]
    if cat:
        sql += " AND v.category=?"
        args.append(cat)
    rows = req.db.q(sql + " ORDER BY v.name COLLATE NOCASE", args)
    total = req.db.val("SELECT COUNT(*) FROM vendors")
    parts = ["<h1>Vendors</h1>"]
    bar = [f'<a class="btn sec" href="/vendors{"" if archived else "?archived=1"}">{"Show active" if archived else "Archived"}</a>']
    if req.can_edit:
        bar.insert(0, '<a class="btn" href="/vendors/new">Add vendor</a>')
    cat_sel = ui.select_("", "category", VENDOR_CATEGORIES, cat, blank="All categories")
    parts.append(f'<form method="get" class="row"><div>{bar[0]}</div><div>{" ".join(bar[1:])}</div>'
                 f'<input type="hidden" name="archived" value="{1 if archived else 0}">{cat_sel}<div><button class="sec">Filter</button></div></form>')
    if total == 0:
        parts.append('<div class="card"><p><b>No vendors yet.</b> Add the first vendor you depend on, or load sample data '
                     'with the command <code>driftwatch demo load</code> and reload this page.</p></div>')
    elif not rows:
        parts.append('<p class="mut">No vendors match.</p>')
    else:
        t = ['<table><tr><th>Vendor</th><th>Category</th><th>Renewal</th><th class="num">Sources</th>'
             '<th class="num">Entries</th><th class="num">Unreviewed</th><th>Status</th></tr>']
        for v in rows:
            status = ui.badge(f"{v['n_failing']} failing", "bad") if v["n_failing"] else ""
            if v["archived"]:
                status += ui.badge("archived")
            t.append(f'<tr><td><a href="/vendors/{v["id"]}">{esc(v["name"])}</a></td><td>{esc(v["category"])}</td>'
                     f'<td>{esc(v["renewal_date"] or "—")}</td><td class="num">{v["n_sources"]}</td>'
                     f'<td class="num">{v["n_entries"]}</td><td class="num">{v["n_unrev"]}</td><td>{status}</td></tr>')
        t.append("</table>")
        parts += t
    return page(req, "Vendors", "".join(parts))


# ------------------------------------------------------------------ vendor form
def _vendor_form(req, v, errors=None, extra=""):
    editing = bool(v.get("id"))
    action = f"/vendors/{v['id']}/edit" if editing else "/vendors/new"
    ver = f'<input type="hidden" name="version" value="{esc(v.get("version", ""))}">' if editing else ""
    body = (f'<h1>{"Edit" if editing else "Add"} vendor</h1>{extra}<div class="card">{ui.error_summary(errors)}'
            f'<form method="post" action="{action}">{req.csrf()}{ver}'
            + ui.field("Name", "name", v.get("name", ""), errors, required=True)
            + ui.select_("Category", "category", VENDOR_CATEGORIES, v.get("category", ""), errors, blank="Choose…")
            + ui.field("Homepage URL (optional)", "homepage", v.get("homepage") or "", errors, "text")
            + ui.field("Renewal date (optional)", "renewal_date", v.get("renewal_date") or "", errors, "date")
            + ui.textarea("Notes (optional)", "notes", v.get("notes") or "", errors)
            + '<p><button>Save</button> <a class="btn sec" href="'
            + (f"/vendors/{v['id']}" if editing else "/vendors") + '">Cancel</a></p></form></div>')
    return body


def _read_vendor(req):
    return {"name": req.get("name"), "category": req.get("category"), "homepage": req.get("homepage"),
            "renewal_date": req.get("renewal_date"), "notes": req.get("notes")}


def _validate_vendor(req, v, vid=None):
    errors, extra = {}, ""
    if not v["name"]:
        errors["name"] = "Name is required"
    elif len(v["name"]) > 120:
        errors["name"] = "Name is too long (max 120)"
    else:
        coll = " COLLATE NOCASE" if req.db.setting("vendors.name_case_insensitive") == "true" else ""
        dup = req.db.one(f"SELECT id FROM vendors WHERE name=?{coll} AND (? IS NULL OR id<>?)", (v["name"], vid, vid))
        if dup:
            errors["name"] = "A vendor with this name exists"
            extra = f'<div class="flash error"><a href="/vendors/{dup["id"]}">Open the existing vendor</a></div>'
    if v["category"] not in VENDOR_CATEGORIES:
        errors["category"] = "Choose a category"
    if v["homepage"] and fetcher.validate_url(v["homepage"]):
        errors["homepage"] = fetcher.validate_url(v["homepage"])
    if v["renewal_date"]:
        try:
            date.fromisoformat(v["renewal_date"])
        except ValueError:
            errors["renewal_date"] = "Enter a valid date (YYYY-MM-DD)"
    return errors, extra


@route("GET", "/vendors/new", role="analyst")
def vendor_new(req):
    return page(req, "Add vendor", _vendor_form(req, {}))


@route("POST", "/vendors/new", role="analyst")
def vendor_create(req):
    v = _read_vendor(req)
    errors, extra = _validate_vendor(req, v)
    if errors:
        return page(req, "Add vendor", _vendor_form(req, v, errors, extra), 400)
    with req.db.tx():
        cur = req.db.x("INSERT INTO vendors(name,category,homepage,renewal_date,notes,created_at,updated_by,updated_at)"
                       " VALUES(?,?,?,?,?,?,?,?)",
                       (v["name"], v["category"], v["homepage"] or None, v["renewal_date"] or None, v["notes"] or None,
                        util.now_iso(), req.user["username"], util.now_iso()))
        req.db.audit(req.user, "vendor.create", {"id": cur.lastrowid, "name": v["name"]})
    return redirect(req, f"/vendors/{cur.lastrowid}", "ok", "Vendor added. Now add a source to watch.")


@route("GET", r"/vendors/(\d+)/edit", role="analyst")
def vendor_edit(req, vid):
    v = _vendor(req, vid)
    return page(req, "Edit vendor", _vendor_form(req, dict(v))) if v else not_found(req, "Vendor")


@route("POST", r"/vendors/(\d+)/edit", role="analyst")
def vendor_update(req, vid):
    cur = _vendor(req, vid)
    if not cur:
        return not_found(req, "Vendor")
    v = _read_vendor(req)
    version = req.int("version", -1)
    errors, extra = _validate_vendor(req, v, int(vid))
    form = {**v, "id": cur["id"], "version": version}
    if errors:
        return page(req, "Edit vendor", _vendor_form(req, form, errors, extra), 400)
    with req.db.tx():
        n = req.db.x("UPDATE vendors SET name=?,category=?,homepage=?,renewal_date=?,notes=?,version=version+1,"
                     "updated_by=?,updated_at=? WHERE id=? AND version=?",
                     (v["name"], v["category"], v["homepage"] or None, v["renewal_date"] or None, v["notes"] or None,
                      req.user["username"], util.now_iso(), cur["id"], version)).rowcount
        if n:
            req.db.audit(req.user, "vendor.update", {"id": cur["id"], "name": v["name"]})
    if not n:
        fresh = _vendor(req, vid)
        return page(req, "Edit vendor", _vendor_form(req, form, None, f'<div class="flash error" role="alert">{esc(conflict_message(req.db, fresh))}</div>'), 409)
    return redirect(req, f"/vendors/{vid}", "ok", "Vendor saved.")


def _set_archived(req, vid, flag):
    cur = _vendor(req, vid)
    if not cur:
        return not_found(req, "Vendor")
    version = req.int("version", -1)
    with req.db.tx():
        n = req.db.x("UPDATE vendors SET archived=?,version=version+1,updated_by=?,updated_at=? WHERE id=? AND version=?",
                     (flag, req.user["username"], util.now_iso(), cur["id"], version)).rowcount
        if n:
            if not flag and req.db.setting("vendors.restore_resumes_fetching") == "false":
                req.db.x("UPDATE sources SET paused=1,version=version+1,updated_by=?,updated_at=? WHERE vendor_id=? AND paused=0",
                         (req.user["username"], util.now_iso(), cur["id"]))
            req.db.audit(req.user, "vendor.archive" if flag else "vendor.restore", {"id": cur["id"], "name": cur["name"]})
    if not n:
        return redirect(req, f"/vendors/{vid}", "error", conflict_message(req.db, _vendor(req, vid)))
    return redirect(req, f"/vendors/{vid}", "ok", "Vendor archived. Fetching stopped; history is kept." if flag else "Vendor restored.")


@route("POST", r"/vendors/(\d+)/archive", role="analyst")
def vendor_archive(req, vid):
    return _set_archived(req, vid, 1)


@route("POST", r"/vendors/(\d+)/restore", role="analyst")
def vendor_restore(req, vid):
    return _set_archived(req, vid, 0)


@route("POST", r"/vendors/(\d+)/purge", role="admin")
def vendor_purge(req, vid):
    v = _vendor(req, vid)
    if not v:
        return not_found(req, "Vendor")
    if req.db.setting("vendors.allow_purge") != "yes" or not v["archived"]:
        return not_allowed(req)
    if req.get("confirm") != v["name"]:
        return redirect(req, f"/vendors/{vid}", "error", "Type the vendor name exactly to confirm the purge.")
    db = req.db
    exports = db.q("SELECT filename FROM exports WHERE vendor_id=?", (vid,))
    with db.tx():
        sids = [r[0] for r in db.q("SELECT id FROM sources WHERE vendor_id=?", (vid,))]
        counts = {"entries": db.val("SELECT COUNT(*) FROM entries WHERE vendor_id=?", (vid,)), "sources": len(sids),
                  "snapshots": 0, "exports": len(exports)}
        db.x("DELETE FROM entry_history WHERE entry_id IN (SELECT id FROM entries WHERE vendor_id=?)", (vid,))
        db.x("DELETE FROM entries WHERE vendor_id=?", (vid,))
        for s in sids:
            counts["snapshots"] += db.val("SELECT COUNT(*) FROM snapshots WHERE source_id=?", (s,))
            db.x("DELETE FROM fetch_log WHERE source_id=?", (s,))
            db.x("DELETE FROM snapshots WHERE source_id=?", (s,))
        db.x("DELETE FROM sources WHERE vendor_id=?", (vid,))
        db.x("DELETE FROM exports WHERE vendor_id=?", (vid,))
        db.x("DELETE FROM vendors WHERE id=?", (vid,))
        db.audit(req.user, "vendor.purge", {"vendor": v["name"], **counts})
    for e in exports:
        (req.cfg.data_dir / "exports" / e["filename"]).unlink(missing_ok=True)
    return redirect(req, "/vendors?archived=1", "ok", f"Vendor {v['name']} and its history were permanently deleted.")


# ------------------------------------------------------------------ vendor detail
def _interval_label(sec):
    m = sec // 60
    if m % 1440 == 0:
        return f"{m // 1440} d"
    if m % 60 == 0:
        return f"{m // 60} h"
    return f"{m} min"


def _source_status(s):
    if s["paused"]:
        return ui.badge("paused")
    if s["failing"]:
        return ui.badge("failing", "bad")
    if s["lock_at"]:
        return ui.badge("fetching", "warn")
    return ui.badge("ok", "ok") if s["last_fetch_at"] else ui.badge("pending")


@route("GET", r"/vendors/(\d+)")
def vendor_detail(req, vid):
    v = _vendor(req, vid)
    if not v:
        return not_found(req, "Vendor")
    cfg, db = req.cfg, req.db
    sources = db.q("SELECT * FROM sources WHERE vendor_id=? ORDER BY id", (vid,))
    p = [f'<h1>{esc(v["name"])} {ui.badge("archived") if v["archived"] else ""}</h1>']
    info = [f'<p>Category: <b>{esc(v["category"])}</b>']
    if v["homepage"]:
        info.append(f' · <a href="{esc(v["homepage"])}" rel="noopener noreferrer nofollow">homepage</a>')
    if v["renewal_date"]:
        info.append(f' · Renewal: <b>{esc(v["renewal_date"])}</b>')
    info.append("</p>")
    if v["notes"]:
        info.append(f'<p style="white-space:pre-wrap">{esc(v["notes"])}</p>')
    p.append('<div class="card">' + "".join(info))
    btns = [f'<a class="btn sec" href="/timeline?vendor={vid}">Timeline</a>',
            f'<a class="btn" href="/vendors/{vid}/evidence">Evidence pack</a>']
    if req.can_edit:
        ver = f'<input type="hidden" name="version" value="{v["version"]}">'
        btns.append(f'<a class="btn sec" href="/vendors/{vid}/edit">Edit</a>')
        if v["archived"]:
            btns.append(f'<form class="inline" method="post" action="/vendors/{vid}/restore">{req.csrf()}{ver}<button class="sec">Restore</button></form>')
        else:
            btns.append(f'<a class="btn sec" href="/vendors/{vid}/sources/new">Add source</a>')
            btns.append(f'<form class="inline" method="post" action="/vendors/{vid}/fetch">{req.csrf()}<button class="sec">Fetch now</button></form>')
            btns.append(f'<form class="inline" method="post" action="/vendors/{vid}/archive">{req.csrf()}{ver}<button class="sec">Archive</button></form>')
    p.append(f'<p>{" ".join(btns)}</p></div>')
    p.append("<h2>Sources</h2>")
    if not sources:
        p.append('<p class="mut">No sources yet.</p>')
    else:
        t = ['<table><tr><th>URL</th><th>Type</th><th>Every</th><th>Status</th><th>Last fetch</th><th>Result</th><th></th></tr>']
        for s in sources:
            act = ""
            if req.can_edit and not v["archived"]:
                act = (f'<form class="inline" method="post" action="/sources/{s["id"]}/fetch">{req.csrf()}'
                       f'<input type="hidden" name="next" value="/vendors/{vid}"><button class="sec">Fetch now</button></form>')
            t.append(f'<tr><td><a href="/sources/{s["id"]}">{esc(s["url"])}</a></td>'
                     f'<td>{esc(SOURCE_TYPE_LABELS.get(s["type"], s["type"]))}</td><td>{_interval_label(s["interval_s"])}</td>'
                     f'<td>{_source_status(s)}</td><td>{ui.local_dt(cfg, s["last_fetch_at"])}</td>'
                     f'<td>{esc((s["last_result"] or "—")[:100])}</td><td>{act}</td></tr>')
        p.append("".join(t) + "</table>")
    recent = db.q("SELECT id,title,status,suggested_category,category,eff_at FROM entries WHERE vendor_id=? "
                  "ORDER BY eff_at DESC,id DESC LIMIT 8", (vid,))
    p.append(f'<h2>Recent changes</h2>')
    if recent:
        p.append("<table><tr><th>Date</th><th>Change</th><th>Category</th><th>Status</th></tr>" + "".join(
            f'<tr><td>{ui.local_dt(cfg, e["eff_at"], "%Y-%m-%d")}</td><td><a href="/entries/{e["id"]}">{esc(e["title"])}</a></td>'
            f'<td>{esc(e["category"] or e["suggested_category"])}</td><td>{ui.status_badge(e["status"])}</td></tr>' for e in recent)
            + f'</table><p><a href="/timeline?vendor={vid}">All changes for this vendor</a></p>')
    else:
        p.append('<p class="mut">No changes recorded yet.</p>')
    exps = db.q("SELECT * FROM exports WHERE vendor_id=? ORDER BY id DESC", (vid,))
    p.append("<h2>Past evidence packs</h2>")
    if exps:
        p.append("<table><tr><th>When</th><th>By</th><th>Range</th><th class='num'>Entries</th><th>Manifest SHA-256</th><th></th></tr>" + "".join(
            f'<tr><td>{ui.local_dt(cfg, x["ts"])}</td><td>{esc(x["username"])}</td><td>{esc(x["range_from"])} – {esc(x["range_to"])}</td>'
            f'<td class="num">{x["entry_count"]}</td><td><code>{esc(x["manifest_hash"][:16])}…</code></td>'
            f'<td><a href="/exports/{x["id"]}/download">Download</a></td></tr>' for x in exps) + "</table>")
    else:
        p.append('<p class="mut">None yet.</p>')
    if req.is_admin and v["archived"] and db.setting("vendors.allow_purge") == "yes":
        p.append(f'<h2>Purge</h2><div class="card"><p>Permanently delete this vendor and all its history. This cannot be undone.</p>'
                 f'<form method="post" action="/vendors/{vid}/purge">{req.csrf()}'
                 + ui.field("Type the vendor name to confirm", "confirm", "") + '<p><button class="danger">Purge vendor</button></p></form></div>')
    return page(req, v["name"], "".join(p))


@route("POST", r"/vendors/(\d+)/fetch", role="analyst")
def vendor_fetch(req, vid):
    v = _vendor(req, vid)
    if not v:
        return not_found(req, "Vendor")
    if v["archived"]:
        return redirect(req, f"/vendors/{vid}", "error", "Archived vendors are not fetched. Restore it first.")
    msgs, new = [], 0
    for s in req.db.q("SELECT id,url FROM sources WHERE vendor_id=? AND paused=0", (vid,)):
        out = ingest.run_fetch(req.db, req.cfg, s["id"])
        new += out.new
        req.db.audit(req.user, "source.fetch", {"source": s["id"], "result": out.result})
        if out.result in ("error", "parse error", "already fetching") or out.result.startswith("blocked"):
            msgs.append(f"{s['url']}: {out.result} ({out.detail})")
    if msgs:
        return redirect(req, f"/vendors/{vid}", "warn", f"Fetched with problems — {new} new entries. " + " | ".join(msgs))
    return redirect(req, f"/vendors/{vid}", "ok", f"Fetch complete: {new} new entries.")


# ------------------------------------------------------------------ source form
def _source_form(req, v, s, errors=None, test=None, anyway=False, banner=""):
    editing = bool(s.get("id"))
    action = f"/sources/{s['id']}/edit" if editing else f"/vendors/{v['id']}/sources/new"
    hidden = ""
    if editing:
        hidden = f'<input type="hidden" name="sid" value="{s["id"]}"><input type="hidden" name="version" value="{esc(s.get("version", ""))}">'
    t = ""
    if test is not None:
        if test["ok"]:
            titles = "".join(f"<li>{esc(x)}</li>" for x in test["titles"])
            warn = "".join(f'<div class="flash warn">{esc(w)}</div>' for w in test["warnings"])
            t = (f'<div class="card"><b>Test fetch OK.</b> Detected type: <b>{esc(SOURCE_TYPE_LABELS.get(test["type"], test["type"]))}</b>'
                 f' · {test["count"]} {"text blocks" if test["type"] == "html" else "items"}. Newest 5:<ul>{titles}</ul>{warn}</div>')
        else:
            t = f'<div class="flash error" role="alert"><b>Test fetch failed:</b> {esc(test["error"])}</div>'
    interval_min = s.get("interval_min")
    if interval_min in (None, ""):
        interval_min = req.db.int_setting("fetch.default_interval_minutes")
    anyway_box = ui.checkbox("Save anyway, even though the test fetch failed", "save_anyway", anyway) if (anyway or (test and not test["ok"])) else ""
    return (f'<h1>{"Edit" if editing else "Add"} source for {esc(v["name"])}</h1>{banner}{t}<div class="card">{ui.error_summary(errors)}'
            f'<form method="post" action="{action}">{req.csrf()}{hidden}'
            + ui.field("URL", "url", s.get("url", ""), errors, required=True, help="For GitHub releases enter owner/repo (or a full URL).")
            + ui.select_("Type", "type", [(k, SOURCE_TYPE_LABELS[k]) for k in SOURCE_TYPES], s.get("type", "auto"), errors,
                         help="Auto-detect inspects the content type and feed autodiscovery links.")
            + ui.field("CSS selector for the changelog region (HTML pages only, optional)", "selector", s.get("selector") or "", errors)
            + ui.field("Fetch interval (minutes, 15 to 10080)", "interval_min", interval_min, errors, "number")
            + anyway_box
            + f'<p><button formaction="/vendors/{v["id"]}/sources/test" class="sec">Test</button> <button>Save</button> '
              f'<a class="btn sec" href="/vendors/{v["id"]}">Cancel</a></p></form></div>')


def _read_source(req):
    return {"url": req.get("url"), "type": req.get("type") or "auto", "selector": req.get("selector"),
            "interval_min": req.get("interval_min")}


def _validate_source(req, v, s, sid=None):
    errors = {}
    if s["type"] not in SOURCE_TYPES:
        errors["type"] = "Choose a source type"
    err = fetcher.check_source_url(s["type"], s["url"]) if s["url"] else "URL is required"
    if err:
        errors["url"] = err
    elif req.db.val("SELECT 1 FROM sources WHERE vendor_id=? AND url=? AND (? IS NULL OR id<>?)", (v["id"], s["url"], sid, sid)):
        errors["url"] = "This vendor already has a source with this URL"
    try:
        m = int(s["interval_min"])
        if not 15 <= m <= 10080:
            raise ValueError
    except ValueError:
        errors["interval_min"] = "Enter a whole number of minutes between 15 and 10080 (7 days)"
    if s["selector"]:
        if s["type"] not in ("html", "auto"):
            errors["selector"] = "A selector only applies to HTML pages"
        else:
            try:
                parsing.parse_selector(s["selector"])
            except ValueError as exc:
                errors["selector"] = str(exc)
    return errors


def _do_test(req, s, loopback_ok=False):
    """The Test button never reaches this machine's own addresses; the pre-save check of a source being saved may."""
    return ingest.test_fetch(req.cfg, s["type"], s["url"], s["selector"], req.db.setting("fetch.robots_txt"), loopback_ok)


@route("GET", r"/vendors/(\d+)/sources/new", role="analyst")
def source_new(req, vid):
    v = _vendor(req, vid)
    if not v:
        return not_found(req, "Vendor")
    if v["archived"]:
        return redirect(req, f"/vendors/{vid}", "error", "Restore the vendor before adding sources.")
    return page(req, "Add source", _source_form(req, v, {}))


@route("POST", r"/vendors/(\d+)/sources/test", role="analyst")
def source_test(req, vid):
    v = _vendor(req, vid)
    if not v:
        return not_found(req, "Vendor")
    s = _read_source(req)
    sid = req.int("sid")
    errors = _validate_source(req, v, s, sid)
    s.update({"id": sid, "version": req.get("version")})
    if errors:
        return page(req, "Test source", _source_form(req, v, s, errors), 400)
    return page(req, "Test source", _source_form(req, v, s, None, _do_test(req, s)))


def _save_source_common(req, v, s, sid):
    """Validate + test. Returns (response or None, resolved type, resolved url)."""
    errors = _validate_source(req, v, s, sid)
    form = {**s, "id": sid, "version": req.get("version")}
    if errors:
        return page(req, "Source", _source_form(req, v, form, errors), 400), None, None
    test = _do_test(req, s, loopback_ok=True)
    anyway = req.get("save_anyway") == "1"
    if not test["ok"] and not anyway:
        return page(req, "Source", _source_form(req, v, form, None, test), 200), None, None
    stype = test["type"] if test["ok"] else s["type"]
    url = test["url"] if test["ok"] and s["type"] == "auto" else s["url"]
    if url != s["url"] and req.db.val("SELECT 1 FROM sources WHERE vendor_id=? AND url=? AND (? IS NULL OR id<>?)", (v["id"], url, sid, sid)):
        return page(req, "Source", _source_form(req, v, form, {"url": "This vendor already has a source with the discovered feed URL"}), 400), None, None
    return None, stype, url


@route("POST", r"/vendors/(\d+)/sources/new", role="analyst")
def source_create(req, vid):
    v = _vendor(req, vid)
    if not v:
        return not_found(req, "Vendor")
    if v["archived"]:
        return not_allowed(req)
    s = _read_source(req)
    resp, stype, url = _save_source_common(req, v, s, None)
    if resp:
        return resp
    with req.db.tx():
        cur = req.db.x("INSERT INTO sources(vendor_id,url,type,selector,interval_s,created_at,updated_by,updated_at)"
                       " VALUES(?,?,?,?,?,?,?,?)",
                       (vid, url, stype, s["selector"] or None, int(s["interval_min"]) * 60, util.now_iso(),
                        req.user["username"], util.now_iso()))
        req.db.audit(req.user, "source.create", {"id": cur.lastrowid, "vendor": v["name"], "url": url, "type": stype})
    out = ingest.run_fetch(req.db, req.cfg, cur.lastrowid)
    kind = "error" if out.failure else "ok"
    return redirect(req, f"/sources/{cur.lastrowid}", kind,
                    f"Source saved. Baseline fetch: {out.result} — {out.detail}" + (f" ({out.new} entries imported)" if out.new else ""))


@route("GET", r"/sources/(\d+)/edit", role="analyst")
def source_edit(req, sid):
    s = _source(req, sid)
    if not s:
        return not_found(req, "Source")
    v = _vendor(req, s["vendor_id"])
    d = dict(s)
    d["interval_min"] = s["interval_s"] // 60
    return page(req, "Edit source", _source_form(req, v, d))


@route("POST", r"/sources/(\d+)/edit", role="analyst")
def source_update(req, sid):
    cur = _source(req, sid)
    if not cur:
        return not_found(req, "Source")
    v = _vendor(req, cur["vendor_id"])
    s = _read_source(req)
    version = req.int("version", -1)
    req.form["sid"] = [str(sid)]
    resp, stype, url = _save_source_common(req, v, s, int(sid))
    if resp:
        return resp
    with req.db.tx():
        n = req.db.x("UPDATE sources SET url=?,type=?,selector=?,interval_s=?,version=version+1,updated_by=?,updated_at=? "
                     "WHERE id=? AND version=?", (url, stype, s["selector"] or None, int(s["interval_min"]) * 60,
                                                  req.user["username"], util.now_iso(), cur["id"], version)).rowcount
        if n:
            req.db.audit(req.user, "source.update", {"id": cur["id"], "url": url})
    if not n:
        fresh = _source(req, sid)
        form = {**s, "id": cur["id"], "version": version}
        return page(req, "Edit source", _source_form(req, v, form, None, None, False,
                    f'<div class="flash error" role="alert">{esc(conflict_message(req.db, fresh))}</div>'), 409)
    return redirect(req, f"/sources/{sid}", "ok", "Source saved.")


@route("POST", r"/sources/(\d+)/(pause|resume)", role="analyst")
def source_pause(req, sid, what):
    s = _source(req, sid)
    if not s:
        return not_found(req, "Source")
    req.db.x("UPDATE sources SET paused=?,version=version+1,updated_by=?,updated_at=? WHERE id=?",
             (1 if what == "pause" else 0, req.user["username"], util.now_iso(), sid))
    req.db.audit(req.user, f"source.{what}", {"id": int(sid)})
    return redirect(req, f"/sources/{sid}", "ok", "Source paused." if what == "pause" else "Source resumed.")


@route("POST", r"/sources/(\d+)/fetch", role="analyst")
def source_fetch(req, sid):
    s = _source(req, sid)
    if not s:
        return not_found(req, "Source")
    v = _vendor(req, s["vendor_id"])
    back = req.get("next") if req.get("next").startswith("/") and not req.get("next").startswith("//") else f"/sources/{sid}"
    if v["archived"]:
        return redirect(req, back, "error", "Archived vendors are not fetched. Restore it first.")
    out = ingest.run_fetch(req.db, req.cfg, int(sid))
    req.db.audit(req.user, "source.fetch", {"source": int(sid), "result": out.result, "new": out.new})
    if out.result == "already fetching":
        return redirect(req, back, "warn", "Already fetching — another fetch of this source is still running.")
    if out.failure:
        return redirect(req, back, "error", f"Fetch failed: {out.result} — {out.detail}")
    return redirect(req, back, "ok", f"Fetch complete: {out.result}. {out.new} new {'entry' if out.new == 1 else 'entries'}.")


# ------------------------------------------------------------------ source detail
@route("GET", r"/sources/(\d+)")
def source_detail(req, sid):
    s = _source(req, sid)
    if not s:
        return not_found(req, "Source")
    v = _vendor(req, s["vendor_id"])
    cfg, db = req.cfg, req.db
    p = [f'<h1>Source: {esc(s["url"])}</h1><p><a href="/vendors/{v["id"]}">&larr; {esc(v["name"])}</a></p>']
    n_entries = db.val("SELECT COUNT(*) FROM entries WHERE source_id=?", (sid,))
    p.append(f'<div class="card"><p>Type: <b>{esc(SOURCE_TYPE_LABELS.get(s["type"], s["type"]))}</b>'
             + (f' · Selector: <code>{esc(s["selector"])}</code>' if s["selector"] else "")
             + f' · Every <b>{_interval_label(s["interval_s"])}</b> · Status: {_source_status(s)}'
             f'<br>Last attempt: {ui.local_dt(cfg, s["last_attempt_at"])} · Last success: {ui.local_dt(cfg, s["last_fetch_at"])}'
             f'<br>Last result: {esc(s["last_result"] or "—")} · New entries in last fetch: {s["last_new"]} · Total entries: '
             f'<a href="/timeline?vendor={v["id"]}&amp;source={sid}">{n_entries}</a>')
    if s["failing"]:
        p.append(f'<br><b>Failing:</b> {s["failures"]} consecutive failed attempts.')
    p.append("</p>")
    if req.can_edit and not v["archived"]:
        p.append(f'<form class="inline" method="post" action="/sources/{sid}/fetch">{req.csrf()}<button>Fetch now</button></form> '
                 f'<a class="btn sec" href="/sources/{sid}/edit">Edit</a> '
                 f'<form class="inline" method="post" action="/sources/{sid}/{"resume" if s["paused"] else "pause"}">{req.csrf()}'
                 f'<button class="sec">{"Resume" if s["paused"] else "Pause"}</button></form>')
    p.append("</div><h2>Fetch log (last 50 attempts)</h2>")
    log = db.q("SELECT * FROM fetch_log WHERE source_id=? ORDER BY id DESC LIMIT 50", (sid,))
    if log:
        p.append("<table><tr><th>Time</th><th>Result</th><th>Detail</th><th>HTTP</th><th class='num'>New</th><th>Snapshot</th></tr>" + "".join(
            f'<tr><td>{ui.local_dt(cfg, r["ts"], "%Y-%m-%d %H:%M:%S")}</td><td>{esc(r["result"])}</td><td>{esc(r["detail"])}</td>'
            f'<td>{esc(r["http_status"] or "")}</td><td class="num">{r["new_entries"]}</td>'
            f'<td>{f"""<a href="/snapshots/{r["snapshot_id"]}">#{r["snapshot_id"]}</a>""" if r["snapshot_id"] else ""}</td></tr>' for r in log) + "</table>")
    else:
        p.append('<p class="mut">No fetches yet.</p>')
    return page(req, "Source", "".join(p))
