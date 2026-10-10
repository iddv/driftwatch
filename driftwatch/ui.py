"""HTML building blocks: layout, forms, formatting."""
from urllib.parse import urlencode

from . import scoring, util
from .util import esc

CSS = """
:root{--fg:#1d2330;--mut:#5d6677;--bg:#f6f7f9;--card:#fff;--bd:#d9dde5;--ac:#1f5fbf;--bad:#b3261e;--ok:#1d7a3e;--warn:#9a6700}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;color:var(--fg);background:var(--bg)}
a{color:var(--ac)}header.top{background:#1d2330;color:#fff;display:flex;gap:1rem;align-items:center;padding:.5rem 1rem;flex-wrap:wrap}
header.top a{color:#d6e2ff;text-decoration:none}header.top a:hover{text-decoration:underline}header.top .brand{font-weight:700;color:#fff;margin-right:1rem}
header.top .sp{flex:1}main{max-width:72rem;margin:1rem auto;padding:0 1rem}
h1{font-size:1.5rem;margin:.5rem 0 1rem}h2{font-size:1.2rem;margin-top:1.5rem}
.card{background:var(--card);border:1px solid var(--bd);border-radius:6px;padding:1rem;margin:1rem 0}
table{border-collapse:collapse;width:100%;background:var(--card)}th,td{border-bottom:1px solid var(--bd);padding:.4rem .6rem;text-align:left;vertical-align:top}
th{background:#eef0f4;font-weight:600}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
label{display:block;font-weight:600;margin:.7rem 0 .2rem}input[type=text],input[type=password],input[type=url],input[type=date],input[type=number],select,textarea{width:100%;max-width:34rem;padding:.4rem .5rem;border:1px solid #9aa3b2;border-radius:4px;font:inherit;background:#fff}
textarea{max-width:48rem;min-height:5rem}.help{color:var(--mut);font-size:.85rem}.err{color:var(--bad);font-size:.9rem;margin:.15rem 0}
input.bad,select.bad,textarea.bad{border-color:var(--bad)}
button,.btn{display:inline-block;padding:.4rem .9rem;border:1px solid var(--ac);background:var(--ac);color:#fff;border-radius:4px;font:inherit;cursor:pointer;text-decoration:none}
button.sec,.btn.sec{background:#fff;color:var(--ac)}button.danger{background:var(--bad);border-color:var(--bad)}
.flash{padding:.6rem .9rem;border-radius:4px;margin:.5rem 0;border:1px solid}.flash.ok{background:#e7f6ec;border-color:#9bd3ae}.flash.error{background:#fdecea;border-color:#f1a9a3}.flash.warn{background:#fff6e0;border-color:#e8cd85}.flash.info{background:#e8f0fd;border-color:#a9c3f1}
.badge{display:inline-block;padding:0 .5rem;border-radius:1rem;font-size:.8rem;border:1px solid var(--bd);background:#eef0f4}
.badge.bad{background:#fdecea;border-color:#f1a9a3;color:var(--bad)}.badge.ok{background:#e7f6ec;border-color:#9bd3ae;color:var(--ok)}.badge.warn{background:#fff6e0;border-color:#e8cd85;color:var(--warn)}
.row{display:flex;gap:.6rem;flex-wrap:wrap;align-items:flex-end}.row>div{min-width:9rem}.row label{margin-top:0}
pre.text{white-space:pre-wrap;word-break:break-word;background:#f3f4f7;border:1px solid var(--bd);padding:.6rem;border-radius:4px;max-height:32rem;overflow:auto}
.before{background:#fdecea}.after{background:#e7f6ec}.mut{color:var(--mut)}.inline{display:inline}
.pager{margin:1rem 0;display:flex;gap:1rem}.heat td.c{text-align:right;font-variant-numeric:tabular-nums}
form.inline button{padding:.2rem .6rem}small{color:var(--mut)}
"""

JS = """
document.addEventListener('change',function(e){var t=e.target;if(t.dataset&&t.dataset.all){document.querySelectorAll('input[name="'+t.dataset.all+'"]').forEach(function(c){c.checked=t.checked})}});
"""


def nav_html(user):
    links = [("/vendors", "Vendors"), ("/timeline", "Timeline"), ("/churn", "Churn")]
    if user and user["role"] in ("analyst", "admin"):
        links.insert(1, ("/triage", "Triage"))
        links.append(("/keywords", "Keywords"))
    if user and user["role"] == "admin":
        links += [("/users", "Users"), ("/audit", "Audit log"), ("/settings", "Settings")]
    out = ['<header class="top"><a class="brand" href="/vendors">Driftwatch</a>']
    out += [f'<a href="{h}">{t}</a>' for h, t in links]
    out.append('<span class="sp"></span>')
    if user:
        out.append(f'<a href="/profile">{esc(user["username"])} ({user["role"]})</a>')
    out.append("</header>")
    return "".join(out)


def layout(title, body, user=None, flashes=(), csrf="", nav=True):
    fl = "".join(f'<div class="flash {esc(k)}" role="status">{esc(m)}</div>' for k, m in flashes)
    logout = (f'<form method="post" action="/logout" class="inline"><input type="hidden" name="_csrf" value="{csrf}">'
              '<button class="sec">Sign out</button></form>') if user else ""
    head = nav_html(user).replace("</header>", logout + "</header>") if nav else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)} · Driftwatch</title><link rel="stylesheet" href="/static/style.css"></head><body>{head}'
            f'<main>{fl}{body}</main><script src="/static/app.js"></script></body></html>')


def qs(**params):
    clean = {k: v for k, v in params.items() if v not in (None, "", [])}
    return urlencode(clean, doseq=True)


def field(label, name, value="", errors=None, type="text", help="", required=False, extra=""):
    err = (errors or {}).get(name)
    cls = ' class="bad"' if err else ""
    e = f'<div class="err" id="err-{name}">{esc(err)}</div>' if err else ""
    h = f'<div class="help">{esc(help)}</div>' if help else ""
    req = " required" if required else ""
    return (f'<div><label for="f-{name}">{esc(label)}</label><input id="f-{name}" type="{type}" name="{name}" '
            f'value="{esc(value)}"{cls}{req} {extra}>{h}{e}</div>')


def textarea(label, name, value="", errors=None, help=""):
    err = (errors or {}).get(name)
    cls = ' class="bad"' if err else ""
    e = f'<div class="err">{esc(err)}</div>' if err else ""
    h = f'<div class="help">{esc(help)}</div>' if help else ""
    return f'<div><label for="f-{name}">{esc(label)}</label><textarea id="f-{name}" name="{name}"{cls}>{esc(value)}</textarea>{h}{e}</div>'


def select_(label, name, options, selected="", errors=None, blank=None, help=""):
    """options: list of values or (value, label)."""
    err = (errors or {}).get(name)
    cls = ' class="bad"' if err else ""
    opts = [f'<option value="">{esc(blank)}</option>'] if blank is not None else []
    for o in options:
        v, l = (o if isinstance(o, tuple) else (o, o))
        sel = " selected" if str(v) == str(selected) else ""
        opts.append(f'<option value="{esc(v)}"{sel}>{esc(l)}</option>')
    e = f'<div class="err">{esc(err)}</div>' if err else ""
    h = f'<div class="help">{esc(help)}</div>' if help else ""
    lab = f'<label for="f-{name}">{esc(label)}</label>' if label else ""
    return f'<div>{lab}<select id="f-{name}" name="{name}"{cls}>{"".join(opts)}</select>{h}{e}</div>'


def checkbox(label, name, checked=False, value="1"):
    return (f'<div><label style="font-weight:400"><input type="checkbox" name="{name}" value="{esc(value)}"'
            f'{" checked" if checked else ""}> {esc(label)}</label></div>')


def local_dt(cfg, s, fmt="%Y-%m-%d %H:%M"):
    if not s:
        return "—"
    dt = util.parse_dt(s)
    if dt is None:
        return esc(s)
    return esc(dt.astimezone(scoring.get_tz(cfg)).strftime(fmt))


def badge(text, kind=""):
    return f'<span class="badge {kind}">{esc(text)}</span>'


def status_badge(st):
    return badge(st, {"reviewed": "ok", "dismissed": "", "unreviewed": "warn"}.get(st, ""))


def impact_badge(i):
    return badge(i, {"high": "bad", "medium": "warn", "low": ""}.get(i, "")) if i else ""


def pager(base_params, page, total, per=50, path=""):
    pages = max(1, -(-total // per))
    bits = []
    if page > 1:
        bits.append(f'<a href="{path}?{qs(**{**base_params, "page": page - 1})}">&larr; Newer</a>')
    bits.append(f"Page {page} of {pages} ({total} total)")
    if page < pages:
        bits.append(f'<a href="{path}?{qs(**{**base_params, "page": page + 1})}">Older &rarr;</a>')
    return f'<div class="pager">{" ".join(bits)}</div>'


def error_summary(errors):
    if not errors:
        return ""
    return '<div class="flash error" role="alert">Please fix the highlighted fields.</div>'
