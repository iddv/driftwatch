"""Users, audit log and settings (F8, M11, M12)."""
from datetime import date

from . import auth, evidence, ui, util
from .db import SETTINGS, CATEGORIES
from .router import route, page, redirect, not_found, Resp
from .util import esc

KEYWORD_CATEGORIES = [c for c in ["deprecation", "removal", "breaking change", "default change", "scope narrowing",
                                  "security", "new capability", "fix"]]


def _user(req, uid):
    return req.db.one("SELECT * FROM users WHERE id=?", (uid,))


@route("GET", "/users", role="admin")
def users(req):
    rows = req.db.q("SELECT * FROM users ORDER BY username COLLATE NOCASE")
    t = ['<h1>Users</h1><p><a class="btn" href="/users/new">Add user</a></p><table><tr><th>Username</th><th>Role</th><th>State</th><th>Actions</th></tr>']
    for u in rows:
        state = ui.badge("active", "ok") if u["active"] else ui.badge("deactivated", "bad")
        if u["must_change"]:
            state += ui.badge("must change password", "warn")
        if u["locked_until"] and util.parse_dt(u["locked_until"]) > util.now():
            state += ui.badge("locked", "bad")
        roles = "".join(f'<option value="{r}"{" selected" if r == u["role"] else ""}>{r}</option>' for r in auth.ROLES)
        acts = (f'<form class="inline" method="post" action="/users/{u["id"]}/role">{req.csrf()}'
                f'<select name="role" aria-label="Role for {esc(u["username"])}">{roles}</select> <button class="sec">Set role</button></form> '
                f'<form class="inline" method="post" action="/users/{u["id"]}/reset">{req.csrf()}<button class="sec">Reset password</button></form> '
                f'<form class="inline" method="post" action="/users/{u["id"]}/{"deactivate" if u["active"] else "reactivate"}">{req.csrf()}'
                f'<button class="sec">{"Deactivate" if u["active"] else "Reactivate"}</button></form>')
        t.append(f'<tr><td>{esc(u["username"])}</td><td>{u["role"]}</td><td>{state}</td><td>{acts}</td></tr>')
    t.append("</table>")
    return page(req, "Users", "".join(t))


def _new_form(req, errors=None, username="", role="analyst"):
    return (f'<h1>Add user</h1><div class="card">{ui.error_summary(errors)}<form method="post" action="/users/new">{req.csrf()}'
            + ui.field("Username", "username", username, errors, required=True)
            + ui.select_("Role", "role", auth.ROLES, role, errors)
            + '<p>A one-time password is generated and shown once.</p><p><button>Create user</button> <a class="btn sec" href="/users">Cancel</a></p></form></div>')


@route("GET", "/users/new", role="admin")
def user_new(req):
    return page(req, "Add user", _new_form(req))


def _show_otp(req, title, username, otp):
    return page(req, title, f'<h1>{esc(title)}</h1><div class="card"><p>One-time password for <b>{esc(username)}</b>. '
                f'It is shown only now; the user must change it at first sign-in.</p>'
                f'<p style="font-size:1.4rem"><code id="otp">{esc(otp)}</code></p><p><a class="btn" href="/users">Back to users</a></p></div>')


@route("POST", "/users/new", role="admin")
def user_create(req):
    username, role = req.get("username"), req.get("role")
    errors = {}
    e = auth.valid_username(username)
    if e:
        errors["username"] = e
    elif req.db.val("SELECT 1 FROM users WHERE username=?", (username,)):
        errors["username"] = "This username is already taken"
    if role not in auth.ROLES:
        errors["role"] = "Choose a role"
    if errors:
        return page(req, "Add user", _new_form(req, errors, username, role), 400)
    otp = auth.one_time_password(req.db)
    with req.db.tx():
        uid = auth.create_user(req.db, username, role, otp, must_change=True)
        req.db.audit(req.user, "user.create", {"id": uid, "username": username, "role": role})
    return _show_otp(req, "User created", username, otp)


@route("POST", r"/users/(\d+)/role", role="admin")
def user_role(req, uid):
    u = _user(req, uid)
    role = req.get("role")
    if not u or role not in auth.ROLES:
        return not_found(req, "User", ("/users", "Users"))
    with req.db.tx():
        if u["role"] == "admin" and role != "admin" and u["active"] and auth.active_admins(req.db) <= 1:
            return redirect(req, "/users", "error", "At least one admin is required")
        req.db.x("UPDATE users SET role=?,version=version+1 WHERE id=?", (role, uid))
        req.db.audit(req.user, "user.role", {"user": u["username"], "from": u["role"], "to": role})
    return redirect(req, "/users", "ok", f"{u['username']} is now {role}.")


@route("POST", r"/users/(\d+)/reset", role="admin")
def user_reset(req, uid):
    u = _user(req, uid)
    if not u:
        return not_found(req, "User", ("/users", "Users"))
    otp = auth.one_time_password(req.db)
    with req.db.tx():
        req.db.x("UPDATE users SET pw_hash=?,must_change=1,failed_count=0,locked_until=NULL,version=version+1 WHERE id=?",
                 (auth.hash_password(otp), uid))
        auth.destroy_user_sessions(req.db, uid)
        req.db.audit(req.user, "user.password_reset", {"user": u["username"]})
    return _show_otp(req, "Password reset", u["username"], otp)


@route("POST", r"/users/(\d+)/(deactivate|reactivate)", role="admin")
def user_active(req, uid, what):
    u = _user(req, uid)
    if not u:
        return not_found(req, "User", ("/users", "Users"))
    with req.db.tx():
        if what == "deactivate":
            if u["role"] == "admin" and u["active"] and auth.active_admins(req.db) <= 1:
                return redirect(req, "/users", "error", "At least one admin is required")
            req.db.x("UPDATE users SET active=0,version=version+1 WHERE id=?", (uid,))
            auth.destroy_user_sessions(req.db, uid)
        else:
            req.db.x("UPDATE users SET active=1,failed_count=0,locked_until=NULL,version=version+1 WHERE id=?", (uid,))
        req.db.audit(req.user, f"user.{what}", {"user": u["username"]})
    return redirect(req, "/users", "ok", f"{u['username']} {what}d.")


# ------------------------------------------------------------------ audit log
@route("GET", "/audit", role="admin")
def audit_log(req):
    where, args, errors = [], [], {}
    user, action = req.get("user"), req.get("action")
    d1, d2 = req.get("from"), req.get("to")
    if user:
        where.append("username=?"); args.append(user)
    if action:
        where.append("action LIKE ?"); args.append(action.replace("%", "") + "%")
    f = t = None
    try:
        f = date.fromisoformat(d1) if d1 else None
    except ValueError:
        errors["from"] = "Enter a valid date"
    try:
        t = date.fromisoformat(d2) if d2 else None
    except ValueError:
        errors["to"] = "Enter a valid date"
    if f and t and f > t:
        errors["to"] = "The end date must not be before the start date"
    if not errors:
        if f:
            where.append("ts>=?"); args.append(evidence.local_range_to_utc(req.cfg, f, f)[0])
        if t:
            where.append("ts<?"); args.append(evidence.local_range_to_utc(req.cfg, t, t)[1])
    w = " AND ".join(where) or "1=1"
    page_no = max(1, req.int("page", 1) or 1)
    names = [r[0] for r in req.db.q("SELECT DISTINCT username FROM audit WHERE username IS NOT NULL ORDER BY username COLLATE NOCASE")]
    form = ('<form method="get" class="row">' + ui.select_("User", "user", names, user, blank="Anyone")
            + ui.field("Action starts with", "action", action, None, help="e.g. login, user, triage")
            + ui.field("From", "from", d1, errors, "date") + ui.field("To", "to", d2, errors, "date")
            + '<div><button>Filter</button> <a class="btn sec" href="/audit">Clear</a></div></form>')
    p = ["<h1>Audit log</h1>", form]
    if errors:
        p.append(ui.error_summary(errors))
    else:
        total = req.db.val(f"SELECT COUNT(*) FROM audit WHERE {w}", args)
        rows = req.db.q(f"SELECT * FROM audit WHERE {w} ORDER BY id DESC LIMIT 100 OFFSET ?", args + [(page_no - 1) * 100])
        if not rows:
            p.append("<p>No audit entries match.</p>")
        else:
            p.append("<table><tr><th>When</th><th>User</th><th>Action</th><th>Detail</th></tr>" + "".join(
                f'<tr><td>{ui.local_dt(req.cfg, r["ts"], "%Y-%m-%d %H:%M:%S")}</td><td>{esc(r["username"] or "—")}</td>'
                f'<td>{esc(r["action"])}</td><td><code>{esc(r["detail"] or "")}</code></td></tr>' for r in rows) + "</table>")
            params = {"user": user, "action": action, "from": d1, "to": d2}
            p.append(ui.pager(params, page_no, total, 100, "/audit"))
    return page(req, "Audit log", "".join(p), 400 if errors else 200)


# ------------------------------------------------------------------ settings
def _settings_page(req, values=None, errors=None, kw_text=None):
    cur = values or req.db.all_settings()
    cfg = req.cfg
    rows = []
    for key, (default, kind, label, spec) in SETTINGS.items():
        if kind == "choice":
            rows.append(ui.select_(f"{label} ({key})", f"s:{key}", spec, cur[key], errors))
        else:
            rows.append(ui.field(f"{label} ({key})", f"s:{key}", cur[key], errors, "number"))
    ro = [("Listen address", cfg.listen), ("Data directory", str(cfg.data_dir)), ("Time zone", cfg.timezone),
          ("Fetch timeout", f"{cfg.fetch_timeout} s"), ("Max response size", util.human_size(cfg.fetch_max_bytes)),
          ("Max redirects", cfg.fetch_max_redirects), ("Concurrent fetches", cfg.fetch_concurrency),
          ("HTTP proxy", "configured" if cfg.http_proxy else "none"), ("GitHub token", "configured" if cfg.github_token else "none")]
    return ("<h1>Settings</h1>" + ui.error_summary(errors)
            + f'<div class="card"><form method="post" action="/settings">{req.csrf()}' + "".join(rows)
            + '<p><button>Save settings</button></p></form></div>'
            + '<p>Keyword rules are edited on the <a href="/keywords">Keywords</a> page.</p>'
            + '<h2>Deployment configuration (read-only; set via environment or config file)</h2><div class="card"><table>'
            + "".join(f"<tr><th style='width:14rem'>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in ro) + "</table></div>")


@route("GET", "/settings", role="admin")
def settings_get(req):
    return page(req, "Settings", _settings_page(req))


@route("POST", "/settings", role="admin")
def settings_post(req):
    new, errors = {}, {}
    for key, (default, kind, label, spec) in SETTINGS.items():
        v = req.get(f"s:{key}")
        new[key] = v
        if kind == "choice":
            if v not in spec:
                errors[f"s:{key}"] = "Choose one of: " + ", ".join(spec)
        else:
            try:
                n = int(v)
                if not spec[0] <= n <= spec[1]:
                    raise ValueError
            except ValueError:
                errors[f"s:{key}"] = f"Enter a whole number between {spec[0]} and {spec[1]}"
    if errors:
        return page(req, "Settings", _settings_page(req, new, errors), 400)
    before = req.db.all_settings()
    changes = {}
    with req.db.tx():
        for k, v in new.items():
            if before[k] != v:
                req.db.set_setting(k, v)
                changes[k] = {"from": before[k], "to": v}
        if changes:
            req.db.audit(req.user, "settings.update", changes)
    return redirect(req, "/settings", "ok", "Settings saved." if changes else "No changes.")


def _keywords_page(req, errors=None, kw_text=None):
    kws = {}
    for r in req.db.q("SELECT category,keyword FROM keyword_rules ORDER BY ord,id"):
        kws.setdefault(r["category"], []).append(r["keyword"])
    boxes = "".join(ui.textarea(c, f"kw:{c}", (kw_text or {}).get(c, "\n".join(kws.get(c, []))), errors) for c in KEYWORD_CATEGORIES)
    return ("<h1>Keyword rules</h1>" + ui.error_summary(errors) + '<div class="card"><p class="help">One keyword per line, '
            "case-insensitive. When several categories match, the one listed first on this page wins. Rules apply to "
            "entries detected from now on.</p>" + f'<form method="post" action="/keywords">{req.csrf()}{boxes}'
            "<p><button>Save keywords</button></p></form></div>")


@route("GET", "/keywords", role="analyst")
def keywords_get(req):
    return page(req, "Keywords", _keywords_page(req))


@route("POST", "/keywords", role="analyst")
def keywords_post(req):
    texts = {c: req.raw(f"kw:{c}") for c in KEYWORD_CATEGORIES}
    rules, errors = [], {}
    for c in KEYWORD_CATEGORIES:
        seen = set()
        for line in texts[c].replace(",", "\n").splitlines():
            k = line.strip()
            if not k or k.lower() in seen:
                continue
            if len(k) > 80:
                errors[f"kw:{c}"] = "Keywords are limited to 80 characters"
            seen.add(k.lower())
            rules.append((c, k))
    if errors:
        return page(req, "Keywords", _keywords_page(req, errors, texts), 400)
    with req.db.tx():
        req.db.x("DELETE FROM keyword_rules")
        for i, (c, k) in enumerate(rules):
            req.db.x("INSERT INTO keyword_rules(category,keyword,ord) VALUES(?,?,?)", (c, k, i))
        req.db.audit(req.user, "settings.keywords", {"rules": len(rules)})
    return redirect(req, "/keywords", "ok", "Keyword rules saved. They apply to entries detected from now on.")
