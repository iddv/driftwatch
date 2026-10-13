"""Triage queue and entry detail/actions (F4), plus the shared entry filter used by the timeline."""
import json
from datetime import date

from . import evidence, scoring, ui, util
from .db import CATEGORIES, IMPACTS, VENDOR_CATEGORIES
from .router import route, page, redirect, not_found, conflict_message, safe_next
from .util import esc

EFF_CAT = "CASE WHEN e.status='reviewed' THEN COALESCE(e.category,e.suggested_category) ELSE e.suggested_category END"
PER_PAGE = 50


def _parse_date(s):
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def build_filter(req, triage=False):
    """Return (where_sql, args, errors, params) from request args."""
    where, args, errors, params = [], [], {}, {}

    def take(name):
        v = req.get(name)
        if v:
            params[name] = v
        return v

    if triage:
        where.append("e.status='unreviewed'")
    if (v := take("vendor")) and v.isdigit():
        where.append("e.vendor_id=?"); args.append(int(v))
    if (v := take("source")) and v.isdigit():
        where.append("e.source_id=?"); args.append(int(v))
    if v := take("vcat"):
        where.append("e.vendor_id IN (SELECT id FROM vendors WHERE category=?)"); args.append(v)
    if triage:
        if v := take("cat"):
            where.append("e.suggested_category=?"); args.append(v)
    else:
        if v := take("cat"):
            where.append(f"({EFF_CAT})=?"); args.append(v)
        if v := take("impact"):
            where.append("e.impact=?"); args.append(v)
        if v := take("status"):
            where.append("e.status=?"); args.append(v)
        if take("affects") == "1":
            where.append("e.affects_us=1")
    d1, d2 = take("from"), take("to")
    f, t = (_parse_date(d1) if d1 else None), (_parse_date(d2) if d2 else None)
    if d1 and not f:
        errors["from"] = "Enter a valid date"
    if d2 and not t:
        errors["to"] = "Enter a valid date"
    if f and t and f > t:
        errors["to"] = "The end date must not be before the start date"
    if not errors:
        if f:
            where.append("e.eff_at>=?"); args.append(evidence.local_range_to_utc(req.cfg, f, f)[0])
        if t:
            where.append("e.eff_at<?"); args.append(evidence.local_range_to_utc(req.cfg, t, t)[1])
    if (q := take("q")):
        like = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(e.title LIKE ? ESCAPE '\\' OR e.text_after LIKE ? ESCAPE '\\' OR e.text_before LIKE ? ESCAPE '\\')")
        args += [like, like, like]
    return (" AND ".join(where) or "1=1"), args, errors, params


def fetch_entries(req, where, args, page_no):
    total = req.db.val(f"SELECT COUNT(*) FROM entries e WHERE {where}", args)
    rows = req.db.q(f"""SELECT e.*, v.name AS vendor_name, ({EFF_CAT}) AS eff_cat FROM entries e
                    JOIN vendors v ON v.id=e.vendor_id WHERE {where}
                    ORDER BY e.eff_at DESC, e.id DESC LIMIT {PER_PAGE} OFFSET ?""", args + [(page_no - 1) * PER_PAGE])
    return total, rows


def entries_table(req, rows, selectable=False):
    cfg = req.cfg
    head = "<th><input type='checkbox' data-all='sel' aria-label='Select all'></th>" if selectable else ""
    out = [f'<table><tr>{head}<th>Date</th><th>Vendor</th><th>Change</th><th>Category</th><th>Impact</th><th>Status</th></tr>']
    for e in rows:
        cb = (f'<td><input type="checkbox" name="sel" value="{e["id"]}:{e["version"]}" aria-label="Select entry {e["id"]}"></td>'
              if selectable else "")
        flags = (ui.badge("backfill") if e["backfill"] else "") + (ui.badge("edited") if e["kind"] == "edited" else "") \
            + (ui.badge("affects us", "bad") if e["affects_us"] else "")
        cat = esc(e["eff_cat"]) + ("" if e["status"] == "reviewed" else ' <small>(suggested)</small>')
        out.append(f'<tr>{cb}<td>{ui.local_dt(cfg, e["eff_at"], "%Y-%m-%d")}</td><td>{esc(e["vendor_name"])}</td>'
                   f'<td><a href="/entries/{e["id"]}">{esc(e["title"])}</a> {flags}</td><td>{cat}</td>'
                   f'<td>{ui.impact_badge(e["impact"])}</td><td>{ui.status_badge(e["status"])}</td></tr>')
    out.append("</table>")
    return "".join(out)


def filter_form(req, params, errors, action, triage=False, extra=""):
    db = req.db
    vendors = [(r["id"], r["name"]) for r in db.q("SELECT id,name FROM vendors ORDER BY name COLLATE NOCASE")]
    cats = ui.select_("Suggested category" if triage else "Change category", "cat", CATEGORIES, params.get("cat", ""), blank="Any")
    parts = [ui.select_("Vendor", "vendor", vendors, params.get("vendor", ""), blank="Any"), cats]
    if not triage:
        parts += [ui.select_("Vendor category", "vcat", VENDOR_CATEGORIES, params.get("vcat", ""), blank="Any"),
                  ui.select_("Impact", "impact", IMPACTS, params.get("impact", ""), blank="Any"),
                  ui.select_("Status", "status", ["unreviewed", "reviewed", "dismissed"], params.get("status", ""), blank="Any")]
    parts += [ui.field("From", "from", params.get("from", ""), errors, "date"), ui.field("To", "to", params.get("to", ""), errors, "date")]
    if not triage:
        parts.append(ui.field("Search text", "q", params.get("q", "")))
        parts.append(ui.checkbox("Affects us", "affects", params.get("affects") == "1"))
    if params.get("source"):
        parts.append(f'<input type="hidden" name="source" value="{esc(params["source"])}">')
    return (f'<form method="get" action="{action}" class="row">{"".join(parts)}<div><button>Filter</button> '
            f'<a class="btn sec" href="{action}">Clear</a></div>{extra}</form>')


# ------------------------------------------------------------------ queue
@route("GET", "/triage", role="analyst")
def triage_queue(req):
    where, args, errors, params = build_filter(req, triage=True)
    page_no = max(1, req.int("page", 1) or 1)
    body = ["<h1>Triage queue</h1>", filter_form(req, params, errors, "/triage", triage=True)]
    if errors:
        body.append(ui.error_summary(errors))
        total, rows = 0, []
    else:
        total, rows = fetch_entries(req, where, args, page_no)
    if not rows and not errors:
        body.append('<div class="card"><p>Nothing to review. New entries appear here after a fetch.</p></div>')
    elif rows:
        nxt = "/triage?" + ui.qs(**params, page=page_no if page_no > 1 else None)
        bulk = (f'<form method="post" action="/triage/bulk">{req.csrf()}<input type="hidden" name="next" value="{esc(nxt)}">'
                + entries_table(req, rows, True)
                + '<div class="card"><b>Apply to selected</b><div class="row">'
                + ui.select_("Category", "category", CATEGORIES, "", blank="—")
                + ui.select_("Impact", "impact", IMPACTS, "low")
                + ui.field("Note (required for high impact)", "note", "")
                + ui.field("Dismiss reason (optional)", "reason", "")
                + '<div><button name="action" value="classify">Classify selected</button> '
                  '<button name="action" value="dismiss" class="sec">Dismiss selected</button></div></div></div></form>')
        body.append(bulk)
        body.append(ui.pager(params, page_no, total, PER_PAGE, "/triage"))
    return page(req, "Triage", "".join(body))


# ------------------------------------------------------------------ entry detail
def _entry(req, eid):
    return req.db.one("""SELECT e.*, v.name AS vendor_name, s.url AS source_url, s.type AS source_type,
                         sn.fetched_at AS fetched_at, sn.sha256 AS snap_sha, ({EFF}) AS eff_cat
                         FROM entries e JOIN vendors v ON v.id=e.vendor_id JOIN sources s ON s.id=e.source_id
                         JOIN snapshots sn ON sn.id=e.snapshot_id WHERE e.id=?""".replace("{EFF}", EFF_CAT), (eid,))


def entry_page(req, e, errors=None, form=None, status=200, banner=""):
    cfg, db = req.cfg, req.db
    form = form or {}
    triage = ' · <a href="/triage">Triage queue</a>' if req.can_edit else ""
    p = [f'<p><a href="/timeline">&larr; Timeline</a>{triage}</p>',
         f'<h1>{esc(e["title"])}</h1>{banner}']
    meta = [("Vendor", f'<a href="/vendors/{e["vendor_id"]}">{esc(e["vendor_name"])}</a>'),
            ("Source", f'<a href="/sources/{e["source_id"]}">{esc(e["source_url"])}</a>'),
            ("Status", ui.status_badge(e["status"]) + (ui.badge("backfill") if e["backfill"] else "")
             + (ui.badge("edited") if e["kind"] == "edited" else "")),
            ("Category", esc(e["category"] if e["status"] == "reviewed" and e["category"] else e["suggested_category"])
             + ("" if e["status"] == "reviewed" else " <small>(keyword suggestion)</small>")),
            ("Impact", ui.impact_badge(e["impact"]) or "—"), ("Affects us", "yes" if e["affects_us"] else "no"),
            ("Published", ui.local_dt(cfg, e["published_at"])), ("Fetched", ui.local_dt(cfg, e["fetched_at"], "%Y-%m-%d %H:%M:%S")),
            ("Detected", ui.local_dt(cfg, e["detected_at"], "%Y-%m-%d %H:%M:%S")),
            ("Snapshot", f'<a href="/snapshots/{e["snapshot_id"]}">View raw snapshot #{e["snapshot_id"]}</a> '
                         f'<small>sha256 {esc(e["snap_sha"][:16])}…</small>')]
    if e["link"]:
        safe = e["link"].lower().startswith(("http://", "https://"))  # never render javascript:/data: links from feeds
        meta.insert(2, ("Link", f'<a href="{esc(e["link"])}" rel="noopener noreferrer nofollow">{esc(e["link"])}</a>' if safe else esc(e["link"])))
    if e["note"]:
        meta.append(("Note", f'<span style="white-space:pre-wrap">{esc(e["note"])}</span>'))
    if e["dismiss_reason"]:
        meta.append(("Dismiss reason", esc(e["dismiss_reason"])))
    if e["reviewed_by"]:
        meta.append(("Reviewed by", f'{esc(e["reviewed_by"])} at {ui.local_dt(cfg, e["reviewed_at"])}'))
    if e["edit_of"]:
        meta.append(("Edits", f'<a href="/entries/{e["edit_of"]}">original entry #{e["edit_of"]}</a>'))
    later = db.q("SELECT id FROM entries WHERE edit_of=?", (e["id"],))
    if later:
        meta.append(("Later edits", ", ".join(f'<a href="/entries/{x["id"]}">#{x["id"]}</a>' for x in later)))
    p.append('<div class="card"><table>' + "".join(f"<tr><th style='width:9rem'>{k}</th><td>{v}</td></tr>" for k, v in meta) + "</table></div>")
    if e["text_before"] is not None:
        p.append(f'<h2>Before</h2><pre class="text before">{esc(e["text_before"])}</pre>')
    if e["text_after"] is not None:
        p.append(f'<h2>{"After" if e["text_before"] is not None else "Original text"}</h2><pre class="text {"after" if e["text_before"] is not None else ""}">{esc(e["text_after"])}</pre>')
    if req.can_edit:
        v = lambda k, d="": form.get(k, d)
        cur_cat = v("category", e["category"] or e["suggested_category"])
        cur_imp = v("impact", e["impact"] or "low")
        ver = f'<input type="hidden" name="version" value="{e["version"]}">'
        err = ui.error_summary(errors)
        p.append('<h2>Triage</h2><div class="card">' + err)
        p.append(f'<form method="post" action="/entries/{e["id"]}/triage">{req.csrf()}{ver}<div class="row">'
                 + ui.select_("Category", "category", CATEGORIES, cur_cat, errors)
                 + ui.select_("Impact", "impact", IMPACTS, cur_imp, errors) + "</div>"
                 + ui.textarea("Note (required for high impact)", "note", v("note", e["note"] or ""), errors)
                 + ui.checkbox("Affects us", "affects_us", bool(int(v("affects_us", e["affects_us"]) or 0)))
                 + f'<p><button>{"Save changes" if e["status"] == "reviewed" else "Save as reviewed"}</button></p></form>')
        if e["status"] != "dismissed":
            p.append(f'<form method="post" action="/entries/{e["id"]}/dismiss">{req.csrf()}{ver}'
                     + ui.field("Dismiss reason (optional)", "reason", form.get("reason", "")) + '<p><button class="sec">Dismiss as noise</button></p></form>')
        if e["status"] != "unreviewed":
            p.append(f'<form method="post" action="/entries/{e["id"]}/reopen">{req.csrf()}{ver}<p><button class="sec">Reopen (back to unreviewed)</button></p></form>')
        p.append("</div>")
    hist = db.q("SELECT * FROM entry_history WHERE entry_id=? ORDER BY id", (e["id"],))
    p.append("<h2>History</h2><table><tr><th>When</th><th>Who</th><th>Action</th><th>Details</th></tr>" + "".join(
        f'<tr><td>{ui.local_dt(cfg, h["ts"], "%Y-%m-%d %H:%M:%S")}</td><td>{esc(h["username"])}</td><td>{esc(h["action"])}</td>'
        f'<td><code>{esc(h["detail"] or "")}</code></td></tr>' for h in hist) + "</table>")
    return page(req, e["title"], "".join(p), status)


@route("GET", r"/entries/(\d+)")
def entry_view(req, eid):
    e = _entry(req, eid)
    return entry_page(req, e) if e else not_found(req, "Entry", ("/triage" if req.can_edit else "/timeline", "the queue" if req.can_edit else "Timeline"))


def _snapshot_triage(e):
    return {"status": e["status"], "category": e["category"], "impact": e["impact"], "note": e["note"],
            "affects_us": e["affects_us"]}


def _apply(db, user, e, action, new, version, reason=None):
    """Optimistic update. Returns True when applied, False on stale version."""
    now = util.now_iso()
    old = _snapshot_triage(e)
    cols = {"status": new["status"], "category": new.get("category"), "impact": new.get("impact"),
            "note": new.get("note"), "affects_us": new.get("affects_us", 0),
            "dismiss_reason": reason if new["status"] == "dismissed" else None,
            "reviewed_by": user["username"] if new["status"] != "unreviewed" else None,
            "reviewed_at": now if new["status"] != "unreviewed" else None}
    sets = ",".join(f"{k}=?" for k in cols)
    n = db.x(f"UPDATE entries SET {sets},version=version+1,updated_by=?,updated_at=? WHERE id=? AND version=?",
             [*cols.values(), user["username"], now, e["id"], version]).rowcount
    if n:
        db.x("INSERT INTO entry_history(entry_id,ts,username,action,detail) VALUES(?,?,?,?,?)",
             (e["id"], now, user["username"], action, json.dumps({"from": old, "to": {**_snapshot_triage({**cols}), "reason": reason}
                                                                  if action == "dismissed" else _snapshot_triage({**cols})})))
        db.audit(user, f"triage.{action}", {"entry": e["id"]})
    return bool(n)


def _stale(req, eid):
    fresh = _entry(req, eid)
    return redirect(req, f"/entries/{eid}", "error", conflict_message(req.db, fresh))


@route("POST", r"/entries/(\d+)/triage", role="analyst")
def entry_triage(req, eid):
    e = _entry(req, eid)
    if not e:
        return not_found(req, "Entry", ("/triage", "the queue"))
    form = {"category": req.get("category"), "impact": req.get("impact"), "note": req.get("note"),
            "affects_us": 1 if req.get("affects_us") else 0}
    errors = {}
    if form["category"] not in CATEGORIES:
        errors["category"] = "Choose a category"
    if form["impact"] not in IMPACTS:
        errors["impact"] = "Choose an impact"
    if form["impact"] == "high" and not form["note"]:
        errors["note"] = "A note is required for high impact"
    if errors:
        return entry_page(req, e, errors, form, 400)
    ok = _apply(req.db, req.user, e, "reviewed" if e["status"] != "reviewed" else "updated",
                {"status": "reviewed", **form}, req.int("version", -1))
    if not ok:
        return _stale(req, eid)
    return redirect(req, safe_next(req.get("next")) if req.get("next") else f"/entries/{eid}", "ok", "Entry saved.")


@route("POST", r"/entries/(\d+)/dismiss", role="analyst")
def entry_dismiss(req, eid):
    e = _entry(req, eid)
    if not e:
        return not_found(req, "Entry", ("/triage", "the queue"))
    ok = _apply(req.db, req.user, e, "dismissed", {"status": "dismissed", "category": None, "impact": None, "note": e["note"]},
                req.int("version", -1), req.get("reason") or None)
    return redirect(req, f"/entries/{eid}", "ok", "Entry dismissed.") if ok else _stale(req, eid)


@route("POST", r"/entries/(\d+)/reopen", role="analyst")
def entry_reopen(req, eid):
    e = _entry(req, eid)
    if not e:
        return not_found(req, "Entry", ("/triage", "the queue"))
    ok = _apply(req.db, req.user, e, "reopened", {"status": "unreviewed"}, req.int("version", -1))
    return redirect(req, f"/entries/{eid}", "ok", "Entry reopened.") if ok else _stale(req, eid)


@route("POST", "/triage/bulk", role="analyst")
def triage_bulk(req):
    nxt = safe_next(req.get("next")) if req.get("next") else "/triage"
    action = req.get("action")
    sel = req.getlist("sel")
    if not sel:
        return redirect(req, nxt, "error", "Select at least one entry.")
    cat, imp, note, reason = req.get("category"), req.get("impact") or "low", req.get("note"), req.get("reason")
    if action == "classify":
        if cat not in CATEGORIES:
            return redirect(req, nxt, "error", "Choose a category to apply.")
        if imp not in IMPACTS:
            return redirect(req, nxt, "error", "Choose a valid impact.")
        if imp == "high" and not note:
            return redirect(req, nxt, "error", "A note is required for high impact.")
    elif action != "dismiss":
        return redirect(req, nxt, "error", "Unknown bulk action.")
    done = stale = 0
    with req.db.tx():
        for item in sel:
            try:
                eid_s, ver_s = item.split(":")
                e = _entry(req, int(eid_s))
                ver = int(ver_s)
                if not -2**62 < ver < 2**62 or not -2**62 < int(eid_s) < 2**62:
                    continue
            except ValueError:
                continue
            if not e:
                continue
            if action == "classify":
                ok = _apply(req.db, req.user, e, "reviewed" if e["status"] != "reviewed" else "updated",
                            {"status": "reviewed", "category": cat, "impact": imp, "note": note or e["note"], "affects_us": e["affects_us"]}, ver)
            else:
                ok = _apply(req.db, req.user, e, "dismissed", {"status": "dismissed", "note": e["note"]}, ver, reason or None)
            done += ok
            stale += not ok
        req.db.audit(req.user, "triage.bulk", {"action": action, "applied": done, "skipped_stale": stale})
    msg = f"{done} entries updated." + (f" {stale} skipped because someone else changed them; reload to see their version." if stale else "")
    return redirect(req, nxt, "warn" if stale else "ok", msg)
