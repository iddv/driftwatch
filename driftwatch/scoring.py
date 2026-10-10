"""Churn scoring, computed from entries at query time."""
from datetime import datetime
from zoneinfo import ZoneInfo

from . import util
from .db import CATEGORIES, BEHAVIOR_SHIFTS


def get_tz(cfg):
    try:
        return ZoneInfo(cfg.timezone)
    except Exception:
        return ZoneInfo("UTC")


def weights(db):
    return {c: db.int_setting(f"weight.{c}") for c in CATEGORIES}


def multipliers(db):
    return {i: db.int_setting(f"impact.{i}") for i in ("low", "medium", "high")}


def entry_counts(e, basis, w, m):
    """Return (category, score) when the entry counts, else None. `e` needs status/category/impact/suggested_category."""
    if e["status"] == "dismissed":
        return None
    if e["status"] == "reviewed":
        cat = e["category"] or e["suggested_category"]
        return cat, w.get(cat, 0) * m.get(e["impact"] or "low", 1)
    if basis == "confirmed_only":
        return None
    return e["suggested_category"], w.get(e["suggested_category"], 0) * 1


def local_month(eff_at: str, tz):
    dt = util.parse_dt(eff_at).astimezone(tz)
    return dt.year, dt.month


def month_range(cfg, n, now=None):
    """Last n months ending with the current one, as [(year, month)] oldest first (display time zone)."""
    tz = get_tz(cfg)
    cur = (now or util.now()).astimezone(tz)
    return [util.add_months(cur.year, cur.month, -(n - 1 - i)) for i in range(n)]


def month_bounds_utc(cfg, year, month):
    tz = get_tz(cfg)
    start = datetime(year, month, 1, tzinfo=tz)
    ny, nm = util.add_months(year, month, 1)
    end = datetime(ny, nm, 1, tzinfo=tz)
    return util.iso(start), util.iso(end)


def churn_table(db, cfg, months=12, vendor_category=None, now=None):
    tz = get_tz(cfg)
    basis = db.setting("churn.count_basis")
    w, m = weights(db), multipliers(db)
    mlist = month_range(cfg, months, now)
    incl = db.setting("churn.trend_includes_current_month") == "true"
    back = max(months, 6 if incl else 7)
    full = month_range(cfg, back, now)
    since, _ = month_bounds_utc(cfg, *full[0])
    vendors = db.q("SELECT * FROM vendors WHERE archived=0" + (" AND category=?" if vendor_category else "")
                   + " ORDER BY name COLLATE NOCASE", (vendor_category,) if vendor_category else ())
    rows = {v["id"]: {"vendor": v, "months": {k: 0 for k in full}, "cats": {c: 0 for c in CATEGORIES}, "total": 0,
                      "recent": 0, "prior": 0, "shifts": 0} for v in vendors}
    excluded = 0
    win = set(mlist)
    recent, prior = (set(full[-3:]), set(full[-6:-3])) if incl else (set(full[-4:-1]), set(full[-7:-4]))
    q = ("SELECT e.vendor_id,e.kind,e.eff_at,e.status,e.category,e.impact,e.suggested_category FROM entries e "
         "JOIN vendors v ON v.id=e.vendor_id WHERE v.archived=0 AND e.eff_at>=?")
    count_edited = db.setting("churn.count_edited") == "true"
    for e in db.q(q, (since,)):
        r = rows.get(e["vendor_id"])
        if r is None or (e["kind"] == "edited" and not count_edited):
            continue
        key = local_month(e["eff_at"], tz)
        if key not in r["months"]:
            continue
        if e["status"] == "unreviewed" and basis == "confirmed_only" and key in win:
            excluded += 1
        res = entry_counts(e, basis, w, m)
        if res is None:
            continue
        cat, score = res
        r["months"][key] += score
        if key in recent:
            r["recent"] += score
        if key in prior:
            r["prior"] += score
        if key in win:
            r["total"] += score
            r["cats"][cat] += 1
            if cat in BEHAVIOR_SHIFTS:
                r["shifts"] += 1
    out = []
    for r in rows.values():
        d = r["recent"] - r["prior"]
        r["trend"] = "up" if d > 0 else "down" if d < 0 else "flat"
        r["trend_delta"] = d
        r["cells"] = [r["months"][k] for k in mlist]
        out.append(r)
    return {"months": mlist, "rows": out, "excluded_unreviewed": excluded, "basis": basis}
