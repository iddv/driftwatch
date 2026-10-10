"""Evidence pack: HTML report, CSV, raw snapshots and a hashed manifest in one zip."""
import csv
import io
import json
import zipfile
from datetime import datetime, timedelta

from . import __version__, scoring, util
from .db import CATEGORIES, IMPACTS
from .util import esc


class ExportTooLarge(Exception):
    pass


def local_range_to_utc(cfg, d_from, d_to):
    """Inclusive local dates -> [start_utc, end_utc) ISO strings."""
    tz = scoring.get_tz(cfg)
    start = datetime(d_from.year, d_from.month, d_from.day, tzinfo=tz)
    nxt = d_to + timedelta(days=1)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz)
    return util.iso(start), util.iso(end)


def select_entries(db, cfg, vendor_id, d_from, d_to, min_impact="low", categories=None):
    start, end = local_range_to_utc(cfg, d_from, d_to)
    include_dismissed = db.setting("export.include_dismissed") == "yes"
    basis_col = "e.detected_at" if db.setting("export.range_basis") == "detected" else "e.eff_at"
    rows = db.q("""SELECT e.*, s.url AS source_url, s.type AS source_type, sn.fetched_at AS fetched_at,
                   sn.sha256 AS snap_sha, sn.size AS snap_size
                   FROM entries e JOIN sources s ON s.id=e.source_id JOIN snapshots sn ON sn.id=e.snapshot_id
                   WHERE e.vendor_id=? AND {col}>=? AND {col}<? ORDER BY e.eff_at, e.id""".replace("{col}", basis_col),
                (vendor_id, start, end))
    need = IMPACTS.index(min_impact) if min_impact in IMPACTS else 0
    out = []
    for e in rows:
        if e["status"] == "dismissed" and not include_dismissed:
            continue
        cat = (e["category"] or e["suggested_category"]) if e["status"] != "unreviewed" else e["suggested_category"]
        if categories and cat not in categories:
            continue
        if need > 0:
            if e["status"] != "reviewed" or IMPACTS.index(e["impact"] or "low") < need:
                continue
        d = dict(e)
        d["eff_category"] = cat
        out.append(d)
    return out


def _cell(v):
    if v is None:
        return ""
    s = str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


CSV_COLUMNS = ["entry_id", "status", "category", "category_is_suggestion", "impact", "affects_us", "kind", "title",
               "published_at", "detected_at", "snapshot_fetched_at", "source_url", "link", "reviewer", "reviewed_at",
               "note", "dismiss_reason", "snapshot_file", "text_before", "text_after"]


def entries_csv(entries) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(CSV_COLUMNS)
    for e in entries:
        w.writerow([e["id"], e["status"], e["eff_category"], "yes" if e["status"] == "unreviewed" else "no",
                    e["impact"] or "", "yes" if e["affects_us"] else "no", e["kind"], _cell(e["title"]),
                    e["published_at"] or "", e["detected_at"], e["fetched_at"], e["source_url"], e["link"] or "",
                    e["reviewed_by"] or "", e["reviewed_at"] or "", _cell(e["note"]), _cell(e["dismiss_reason"]),
                    f"snapshots/snapshot-{e['snapshot_id']}.raw", _cell(e["text_before"]), _cell(e["text_after"])])
    return buf.getvalue().encode("utf-8")


def _fmt(cfg, s):
    if not s:
        return "—"
    return util.parse_dt(s).astimezone(scoring.get_tz(cfg)).strftime("%Y-%m-%d %H:%M %Z")


def report_html(db, cfg, vendor, entries, d_from, d_to, min_impact, categories, generated) -> bytes:
    tz = scoring.get_tz(cfg)
    by_cat, by_month = {}, {}
    for e in entries:
        by_cat[e["eff_category"]] = by_cat.get(e["eff_category"], 0) + 1
        y, m = scoring.local_month(e["eff_at"], tz)
        by_month[f"{y}-{m:02d}"] = by_month.get(f"{y}-{m:02d}", 0) + 1
    p = []
    p.append("<!doctype html><html lang=en><head><meta charset=utf-8>"
             f"<title>Evidence pack: {esc(vendor['name'])}</title><style>"
             "body{font:15px/1.5 system-ui,sans-serif;max-width:60rem;margin:2rem auto;padding:0 1rem;color:#1a1a1a}"
             "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:.25rem .6rem;text-align:left}"
             "pre{white-space:pre-wrap;background:#f5f5f5;padding:.6rem;border-radius:4px}"
             ".entry{border-top:2px solid #333;margin-top:1.5rem;padding-top:.5rem}.dis{color:#a00}"
             "</style></head><body>")
    p.append(f"<h1>Evidence pack: {esc(vendor['name'])}</h1>")
    p.append(f"<p>Vendor category: {esc(vendor['category'])}. Range checked: <b>{d_from} to {d_to}</b> "
             f"(time zone {esc(cfg.timezone)}). Minimum impact: {esc(min_impact)}. Categories: "
             f"{esc(', '.join(categories) if categories else 'all')}.<br>Generated {esc(_fmt(cfg, util.iso(generated)))} "
             f"by Driftwatch {esc(__version__)}. File hashes are listed in manifest.json.</p>")
    p.append(f"<p><b>{len(entries)}</b> entries included.</p>")
    if not entries:
        p.append("<p>No entries matched this range and these filters. This empty pack documents that the range above was checked.</p>")
    else:
        p.append("<h2>Summary by category</h2><table><tr><th>Category</th><th>Entries</th></tr>")
        for c in CATEGORIES:
            if c in by_cat:
                p.append(f"<tr><td>{esc(c)}</td><td>{by_cat[c]}</td></tr>")
        p.append("</table><h2>Summary by month</h2><table><tr><th>Month</th><th>Entries</th></tr>")
        for k in sorted(by_month):
            p.append(f"<tr><td>{k}</td><td>{by_month[k]}</td></tr>")
        p.append("</table><h2>Entries</h2>")
    for e in entries:
        dis = " <span class=dis>[DISMISSED]</span>" if e["status"] == "dismissed" else ""
        p.append(f"<div class=entry><h3>#{e['id']} {esc(e['title'])}{dis}</h3><table>")
        rows = [("Source URL", e["source_url"]), ("Link", e["link"]), ("Published", _fmt(cfg, e["published_at"])),
                ("Fetched", _fmt(cfg, e["fetched_at"])), ("Detected", _fmt(cfg, e["detected_at"])),
                ("Status", e["status"]),
                ("Category", e["eff_category"] + (" (keyword suggestion, not reviewed)" if e["status"] == "unreviewed" else "")),
                ("Impact", e["impact"] or "—"), ("Affects us", "yes" if e["affects_us"] else "no"),
                ("Reviewer", f"{e['reviewed_by'] or '—'} at {_fmt(cfg, e['reviewed_at'])}"),
                ("Note", e["note"] or "—"), ("Kind", e["kind"] + (" (backfill)" if e["backfill"] else "")),
                ("Snapshot", f"snapshots/snapshot-{e['snapshot_id']}.raw  sha256 {e['snap_sha']}")]
        if e["dismiss_reason"]:
            rows.append(("Dismiss reason", e["dismiss_reason"]))
        for k, v in rows:
            p.append(f"<tr><th>{k}</th><td>{esc(v)}</td></tr>")
        p.append("</table>")
        if e["text_before"] is not None:
            p.append(f"<p><b>Before</b></p><pre>{esc(e['text_before'])}</pre>")
        if e["text_after"] is not None:
            p.append(f"<p><b>{'After' if e['text_before'] is not None else 'Original text'}</b></p><pre>{esc(e['text_after'])}</pre>")
        p.append("</div>")
    p.append("</body></html>")
    return "\n".join(p).encode("utf-8")


VERIFY_TXT = """Verify this evidence pack
=========================
manifest.json lists every other file in this archive with its SHA-256 hash.
From the unpacked directory run:

    python3 -c "import json,hashlib;m=json.load(open('manifest.json'));\\
bad=[f['path'] for f in m['files'] if hashlib.sha256(open(f['path'],'rb').read()).hexdigest()!=f['sha256']];\\
print('OK' if not bad else 'MISMATCH: %s' % bad)"

or, with GNU coreutils:  sha256sum -c <(python3 -c "import json;[print(f['sha256'],' ',f['path']) for f in json.load(open('manifest.json'))['files']]")

The SHA-256 of manifest.json itself is recorded in the Driftwatch audit log when the pack is exported.
Snapshot files are the exact bytes fetched from the vendor source.
"""


def estimate_size(db, entries) -> int:
    seen = {}
    for e in entries:
        seen[e["snapshot_id"]] = e["snap_size"]
    return sum(seen.values())


def build_pack(db, cfg, vendor, d_from, d_to, min_impact, categories, user):
    entries = select_entries(db, cfg, vendor["id"], d_from, d_to, min_impact, categories)
    limit = db.int_setting("export.max_mb") * 1024 * 1024
    est = estimate_size(db, entries)
    if est > limit:
        raise ExportTooLarge(f"Export would be about {util.human_size(est)}, above the "
                             f"{db.int_setting('export.max_mb')} MB limit. Narrow the date range.")
    generated = util.now()
    files = {}
    files["report.html"] = report_html(db, cfg, vendor, entries, d_from, d_to, min_impact, categories, generated)
    files["entries.csv"] = entries_csv(entries)
    files["VERIFY.txt"] = VERIFY_TXT.encode()
    for sid in sorted({e["snapshot_id"] for e in entries}):
        body = db.val("SELECT body FROM snapshots WHERE id=?", (sid,))
        files[f"snapshots/snapshot-{sid}.raw"] = bytes(body)
    manifest = {
        "generator": f"Driftwatch {__version__}", "generated_at": util.iso(generated),
        "vendor": vendor["name"], "range": {"from": str(d_from), "to": str(d_to), "time_zone": cfg.timezone},
        "min_impact": min_impact, "categories": categories or "all", "entry_count": len(entries),
        "files": [{"path": p, "sha256": util.sha256(b), "size": len(b)} for p, b in sorted(files.items())],
    }
    mbytes = json.dumps(manifest, indent=2, sort_keys=True).encode()
    mhash = util.sha256(mbytes)
    safe = "".join(c if c.isalnum() else "-" for c in vendor["name"].lower()).strip("-") or "vendor"
    fname = f"evidence-{safe}-{d_from}-to-{d_to}-{mhash[:8]}.zip"
    path = cfg.data_dir / "exports" / fname
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for p, b in sorted(files.items()):
            z.writestr(zipfile.ZipInfo(p, date_time=generated.timetuple()[:6]), b, zipfile.ZIP_DEFLATED)
        z.writestr(zipfile.ZipInfo("manifest.json", date_time=generated.timetuple()[:6]), mbytes, zipfile.ZIP_DEFLATED)
    size = path.stat().st_size
    with db.tx():
        cur = db.x("INSERT INTO exports(vendor_id,username,ts,range_from,range_to,min_impact,categories,entry_count,"
                   "manifest_hash,filename,size) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (vendor["id"], user["username"], util.iso(generated), str(d_from), str(d_to), min_impact,
                    ",".join(categories) if categories else "", len(entries), mhash, fname, size))
        db.audit(user, "export.evidence", {"vendor": vendor["name"], "from": str(d_from), "to": str(d_to),
                                           "entries": len(entries), "manifest_sha256": mhash, "export_id": cur.lastrowid})
    return {"id": cur.lastrowid, "path": path, "filename": fname, "manifest_hash": mhash, "count": len(entries)}
