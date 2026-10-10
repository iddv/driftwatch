"""Timeline, snapshots, churn report and evidence packs (F5, F6, F7)."""
import calendar
import csv
import io
from datetime import date, timedelta

from . import evidence, scoring, ui, util
from .db import CATEGORIES, IMPACTS
from .router import route, page, redirect, not_found, download, Resp
from .util import esc
from . import v_triage


# ------------------------------------------------------------------ timeline
@route("GET", "/timeline")
def timeline(req):
    where, args, errors, params = v_triage.build_filter(req)
    page_no = max(1, req.int("page", 1) or 1)
    body = ["<h1>Timeline</h1>", v_triage.filter_form(req, params, errors, "/timeline")]
    if errors:
        body.append(ui.error_summary(errors))
    else:
        total, rows = v_triage.fetch_entries(req, where, args, page_no)
        if not rows:
            body.append('<div class="card"><p>No changes match.</p><p><a class="btn sec" href="/timeline">Clear filters</a></p></div>')
        else:
            body.append(v_triage.entries_table(req, rows))
            body.append(ui.pager(params, page_no, total, v_triage.PER_PAGE, "/timeline"))
            body.append('<p class="help">Share this filtered view by copying the address bar URL.</p>')
    return page(req, "Timeline", "".join(body), 400 if errors else 200)


# ------------------------------------------------------------------ snapshots
@route("GET", r"/snapshots/(\d+)")
def snapshot_view(req, sid):
    s = req.db.one("SELECT id,source_id,fetched_at,http_status,sha256,content_type,size,parse_ok FROM snapshots WHERE id=?", (sid,))
    if not s:
        return not_found(req, "Snapshot", ("/timeline", "Timeline"))
    src = req.db.one("SELECT s.url,v.name,v.id AS vid FROM sources s JOIN vendors v ON v.id=s.vendor_id WHERE s.id=?", (s["source_id"],))
    body = bytes(req.db.val("SELECT body FROM snapshots WHERE id=?", (sid,)))
    shown = body[:2_000_000].decode("utf-8", errors="replace")
    note = " (display truncated; download for the full bytes)" if len(body) > 2_000_000 else ""
    p = [f'<h1>Raw snapshot #{s["id"]}</h1><p><a href="/sources/{s["source_id"]}">{esc(src["url"])}</a> — {esc(src["name"])}</p>',
         '<div class="card"><table>'
         f'<tr><th style="width:9rem">Fetched</th><td>{ui.local_dt(req.cfg, s["fetched_at"], "%Y-%m-%d %H:%M:%S")}</td></tr>'
         f'<tr><th>HTTP status</th><td>{esc(s["http_status"])}</td></tr><tr><th>Content type</th><td>{esc(s["content_type"])}</td></tr>'
         f'<tr><th>Size</th><td>{s["size"]} bytes</td></tr><tr><th>SHA-256</th><td><code>{esc(s["sha256"])}</code></td></tr>'
         f'<tr><th>Parsed</th><td>{"yes" if s["parse_ok"] else "no (parse error; raw body kept for inspection)"}</td></tr></table>'
         f'<p><a class="btn sec" href="/snapshots/{sid}/raw">Download exact bytes</a></p></div>'
         f'<h2>Stored response{note}</h2><p class="help">Shown as escaped text; fetched content is never rendered or executed.</p>'
         f'<pre class="text">{esc(shown)}</pre>']
    return page(req, f"Snapshot {sid}", "".join(p))


@route("GET", r"/snapshots/(\d+)/raw")
def snapshot_raw(req, sid):
    r = req.db.one("SELECT body FROM snapshots WHERE id=?", (sid,))
    if not r:
        return not_found(req, "Snapshot", ("/timeline", "Timeline"))
    return download(bytes(r[0]), f"snapshot-{sid}.raw")


# ------------------------------------------------------------------ churn
def _sorted_rows(rows, sort, direction):
    keyf = (lambda r: r["total"]) if sort == "total" else (lambda r: r["cats"].get(sort, 0))
    rows = sorted(rows, key=lambda r: r["vendor"]["name"].lower())
    return sorted(rows, key=keyf, reverse=(direction != "asc"))


def _churn_args(req):
    months = req.int("months", 12)
    if months not in (3, 6, 12, 24):
        months = 12
    sort = req.get("sort") or "total"
    if sort != "total" and sort not in CATEGORIES:
        sort = "total"
    direction = "asc" if req.get("dir") == "asc" else "desc"
    return months, req.get("vcat"), sort, direction


def _trend_text(r):
    sym = {"up": "▲", "down": "▼", "flat": "▬"}[r["trend"]]
    d = r["trend_delta"]
    return f"{sym} {'+' if d > 0 else ''}{d}" if d else f"{sym} 0"


@route("GET", "/churn")
def churn(req):
    months, vcat, sort, direction = _churn_args(req)
    data = scoring.churn_table(req.db, req.cfg, months, vcat)
    rows = _sorted_rows(data["rows"], sort, direction)
    from .db import VENDOR_CATEGORIES
    base = {"months": months, "vcat": vcat}
    ctrl = (f'<form method="get" class="row">'
            + ui.select_("Period", "months", [(3, "3 months"), (6, "6 months"), (12, "12 months"), (24, "24 months")], months)
            + ui.select_("Vendor category", "vcat", VENDOR_CATEGORIES, vcat or "", blank="All")
            + f'<input type="hidden" name="sort" value="{esc(sort)}"><input type="hidden" name="dir" value="{direction}">'
            f'<div><button>Apply</button> <a class="btn sec" href="/churn.csv?{ui.qs(**base, sort=sort, dir=direction)}">Export CSV</a></div></form>')
    p = ["<h1>Churn report</h1>", ctrl]
    if data["basis"] == "confirmed_only" and data["excluded_unreviewed"]:
        link = f' <a href="/triage">Open the triage queue</a>' if req.can_edit else ""
        p.append(f'<div class="flash warn">{data["excluded_unreviewed"]} unreviewed entries in this period are excluded '
                 f'because churn counts confirmed entries only.{link}</div>')
    n_entries = sum(sum(r["cats"].values()) for r in rows)
    if not rows:
        p.append('<div class="card"><p>No active vendors yet. Scores appear after fetches and triage.</p></div>')
        return page(req, "Churn", "".join(p))
    if n_entries == 0 and not any(r["total"] for r in rows):
        p.append('<div class="card"><p>No scored entries in this period. Scores appear after fetches and triage.</p></div>')

    def th(label, key=None):
        if not key:
            return f"<th>{esc(label)}</th>"
        nd = "asc" if (sort == key and direction == "desc") else "desc"
        arrow = (" ▼" if direction == "desc" else " ▲") if sort == key else ""
        return f'<th class="num"><a href="/churn?{ui.qs(**base, sort=key, dir=nd)}">{esc(label)}{arrow}</a></th>'

    head = ["<th>Vendor</th>"] + [f'<th class="num">{y}-{m:02d}</th>' for y, m in data["months"]] + \
        [th("Total", "total")] + [th(c, c) for c in CATEGORIES] + ["<th>Trend (3 vs prior 3 mo)</th>"]
    t = ['<div style="overflow-x:auto"><table class="heat"><tr>' + "".join(head) + "</tr>"]
    for r in rows:
        v = r["vendor"]
        cells = []
        for (y, m), score in zip(data["months"], r["cells"]):
            last = calendar.monthrange(y, m)[1]
            href = f'/timeline?{ui.qs(vendor=v["id"], **{"from": f"{y}-{m:02d}-01", "to": f"{y}-{m:02d}-{last:02d}"})}'
            cells.append(f'<td class="c"><a href="{href}">{score}</a></td>')
        t.append(f'<tr><td><a href="/vendors/{v["id"]}">{esc(v["name"])}</a><br><small>{esc(v["category"])}</small></td>'
                 + "".join(cells) + f'<td class="num"><b>{r["total"]}</b></td>'
                 + "".join(f'<td class="num">{r["cats"][c]}</td>' for c in CATEGORIES) + f'<td>{esc(_trend_text(r))}</td></tr>')
    t.append("</table></div>")
    p += t
    p.append('<p class="help">Cell = churn score for that vendor and month (category weight × impact multiplier; '
             'unreviewed entries count at ×1 unless the operator setting says confirmed only; dismissed never count). '
             'Category columns count entries in the period. Click a score to see its entries.</p>')
    return page(req, "Churn", "".join(p))


@route("GET", "/churn.csv")
def churn_csv(req):
    months, vcat, sort, direction = _churn_args(req)
    data = scoring.churn_table(req.db, req.cfg, months, vcat)
    rows = _sorted_rows(data["rows"], sort, direction)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["Vendor", "Vendor category"] + [f"{y}-{m:02d}" for y, m in data["months"]] + ["Total"] + CATEGORIES + ["Trend"])
    for r in rows:
        w.writerow([evidence._cell(r["vendor"]["name"]), r["vendor"]["category"]] + r["cells"] + [r["total"]]
                   + [r["cats"][c] for c in CATEGORIES] + [_trend_text(r)])
    return download(buf.getvalue().encode("utf-8-sig"), f"driftwatch-churn-{util.now().strftime('%Y%m%d')}.csv", "text/csv; charset=utf-8")


# ------------------------------------------------------------------ evidence pack
def _default_range(req, v):
    tz = scoring.get_tz(req.cfg)
    today = util.now().astimezone(tz).date()
    to = today
    if v["renewal_date"]:
        try:
            to = date.fromisoformat(v["renewal_date"])
        except ValueError:
            pass
    y, m = util.add_months(to.year, to.month, -12)
    d = min(to.day, calendar.monthrange(y, m)[1])
    return date(y, m, d), to


def _evidence_form(req, v, vals, errors=None, warn="", count=None):
    cats = vals.get("categories", [])
    boxes = "".join(ui.checkbox(c, "categories", c in cats, c) for c in CATEGORIES)
    confirm = '<input type="hidden" name="confirm_empty" value="1">' if warn else ""
    return (f'<h1>Evidence pack: {esc(v["name"])}</h1><p><a href="/vendors/{v["id"]}">&larr; {esc(v["name"])}</a></p>'
            f'{warn}<div class="card">{ui.error_summary(errors)}<form method="post" action="/vendors/{v["id"]}/evidence">{req.csrf()}{confirm}'
            '<div class="row">' + ui.field("From", "from", vals["from"], errors, "date", required=True)
            + ui.field("To", "to", vals["to"], errors, "date", required=True)
            + ui.select_("Minimum impact", "min_impact", [("low", "Any (low and up, incl. unreviewed)"), ("medium", "Medium and up"), ("high", "High only")], vals["min_impact"], errors)
            + f'</div><label>Categories (none ticked = all)</label>{boxes}'
            f'<p><button>{"Export empty pack" if warn else "Build and download pack"}</button></p></form></div>')


@route("GET", r"/vendors/(\d+)/evidence")
def evidence_form(req, vid):
    v = req.db.one("SELECT * FROM vendors WHERE id=?", (vid,))
    if not v:
        return not_found(req, "Vendor")
    f, t = _default_range(req, v)
    return page(req, "Evidence pack", _evidence_form(req, v, {"from": str(f), "to": str(t), "min_impact": "low", "categories": []}))


@route("POST", r"/vendors/(\d+)/evidence")
def evidence_build(req, vid):
    v = req.db.one("SELECT * FROM vendors WHERE id=?", (vid,))
    if not v:
        return not_found(req, "Vendor")
    vals = {"from": req.get("from"), "to": req.get("to"), "min_impact": req.get("min_impact") or "low",
            "categories": [c for c in req.getlist("categories") if c in CATEGORIES]}
    errors = {}
    d1 = d2 = None
    try:
        d1 = date.fromisoformat(vals["from"])
    except ValueError:
        errors["from"] = "Enter a valid date"
    try:
        d2 = date.fromisoformat(vals["to"])
    except ValueError:
        errors["to"] = "Enter a valid date"
    if d1 and d2 and d1 > d2:
        errors["to"] = "The end date must not be before the start date"
    if vals["min_impact"] not in IMPACTS:
        errors["min_impact"] = "Choose a valid impact"
    if errors:
        return page(req, "Evidence pack", _evidence_form(req, v, vals, errors), 400)
    entries = evidence.select_entries(req.db, req.cfg, v["id"], d1, d2, vals["min_impact"], vals["categories"])
    if not entries and req.get("confirm_empty") != "1":
        warn = '<div class="flash warn">No entries match this range and these filters. You can still export an empty pack that states the range checked.</div>'
        return page(req, "Evidence pack", _evidence_form(req, v, vals, None, warn))
    try:
        res = evidence.build_pack(req.db, req.cfg, v, d1, d2, vals["min_impact"], vals["categories"], req.user)
    except evidence.ExportTooLarge as exc:
        return page(req, "Evidence pack", _evidence_form(req, v, vals, {"to": str(exc)}), 400)
    return download(res["path"].read_bytes(), res["filename"], "application/zip")


@route("GET", r"/exports/(\d+)/download")
def export_download(req, xid):
    x = req.db.one("SELECT * FROM exports WHERE id=?", (xid,))
    p = req.cfg.data_dir / "exports" / x["filename"] if x else None
    if not x or not p.is_file():
        return not_found(req, "Export")
    return download(p.read_bytes(), x["filename"], "application/zip")
