"""Setup, sign-in, sign-out and own-password views."""
from . import auth, ui, util
from .router import route, page, redirect, Resp, safe_next
from .util import esc


def _secure(req):
    """True when a reverse proxy says the request arrived over HTTPS."""
    for k, v in req.headers.items():
        if k.lower() == "x-forwarded-proto":
            return v.split(",")[0].strip().lower() == "https"
    return False


def _set_session(req, resp, token):
    resp.cookies.append(f"dw_sess={token}; Path=/; HttpOnly; SameSite=Lax" + ("; Secure" if _secure(req) else ""))


@route("GET", "/", role=None)
def index(req):
    return redirect(req, "/vendors")


def _setup_form(req, errors=None, username=""):
    return (f'<div class="card" style="max-width:34rem"><h1>Welcome to Driftwatch</h1>'
            '<p>Create the admin account to finish setup. This page is only available until an admin exists, so set up a network-exposed install at once.</p>'
            f'{ui.error_summary(errors)}<form method="post" action="/setup">{req.csrf()}'
            + ui.field("Admin username", "username", username, errors, required=True)
            + ui.field("Password", "password", "", errors, "password", f"At least {req.db.int_setting('auth.min_password')} characters", True, 'autocomplete="new-password"')
            + ui.field("Repeat password", "password2", "", errors, "password", required=True, extra='autocomplete="new-password"')
            + '<p><button>Create admin and sign in</button></p></form></div>')


@route("GET", "/setup", role=None)
def setup_get(req):
    if auth.admin_exists(req.db):
        return redirect(req, "/login")
    return page(req, "Setup", _setup_form(req), nav=False)


@route("POST", "/setup", role=None)
def setup_post(req):
    if auth.admin_exists(req.db):
        return redirect(req, "/login")
    username, pw, pw2 = req.get("username"), req.raw("password"), req.raw("password2")
    errors = {}
    e = auth.valid_username(username)
    if e:
        errors["username"] = e
    elif req.db.val("SELECT 1 FROM users WHERE username=?", (username,)):
        errors["username"] = "This username is taken"
    e = auth.password_error(req.db, pw)
    if e:
        errors["password"] = e
    elif pw != pw2:
        errors["password2"] = "The two passwords do not match"
    if errors:
        return page(req, "Setup", _setup_form(req, errors, username), 400, nav=False)
    with req.db.tx():
        if auth.admin_exists(req.db):
            return redirect(req, "/login")
        uid = auth.create_user(req.db, username, "admin", pw)
        user = req.db.one("SELECT * FROM users WHERE id=?", (uid,))
        req.db.audit(user, "setup.admin_created")
    tok = auth.create_session(req.db, uid)
    resp = redirect(req, "/vendors")
    _set_session(req, resp, tok)
    return resp


def _login_form(req, error="", username="", nxt=""):
    err = f'<div class="flash error" role="alert">{esc(error)}</div>' if error else ""
    return (f'<div class="card" style="max-width:26rem;margin:3rem auto"><h1>Sign in</h1>{err}'
            f'<form method="post" action="/login">{req.csrf()}<input type="hidden" name="next" value="{esc(nxt)}">'
            + ui.field("Username", "username", username, required=True, extra="autofocus")
            + ui.field("Password", "password", "", None, "password", required=True, extra='autocomplete="current-password"')
            + '<p><button>Sign in</button></p></form></div>')


@route("GET", "/login", role=None)
def login_get(req):
    if not auth.admin_exists(req.db):
        return redirect(req, "/setup")
    if req.user:
        return redirect(req, "/vendors")
    return page(req, "Sign in", _login_form(req, nxt=req.get("next")), nav=False)


@route("POST", "/login", role=None)
def login_post(req):
    if not auth.admin_exists(req.db):
        return redirect(req, "/setup")
    res = auth.authenticate(req.db, req.get("username"), req.raw("password"))
    if res.error:
        return page(req, "Sign in", _login_form(req, res.error, req.get("username"), req.get("next")), 200, nav=False)
    tok = auth.create_session(req.db, res.user["id"])
    dest = "/profile/password" if res.user["must_change"] else safe_next(req.get("next"))
    resp = redirect(req, dest)
    _set_session(req, resp, tok)
    return resp


@route("POST", "/logout", role=None)
def logout(req):
    if req.user:
        req.db.audit(req.user, "logout")
    auth.destroy_session(req.db, req.token)
    resp = redirect(req, "/login")
    resp.cookies.append("dw_sess=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0" + ("; Secure" if _secure(req) else ""))
    return resp


@route("GET", "/profile")
def profile(req):
    u = req.user
    body = (f'<h1>Profile</h1><div class="card"><p>Signed in as <b>{esc(u["username"])}</b> — role <b>{u["role"]}</b>.</p>'
            '<p><a class="btn sec" href="/profile/password">Change password</a></p></div>')
    return page(req, "Profile", body)


def _pw_form(req, errors=None):
    forced = req.user["must_change"]
    note = ('<div class="flash warn">Your password is a one-time password. Choose a new one to continue.</div>'
            if forced else "")
    return (f'<h1>Change password</h1>{note}<div class="card">{ui.error_summary(errors)}'
            f'<form method="post" action="/profile/password">{req.csrf()}'
            + ui.field("Current password", "current", "", errors, "password", required=True, extra='autocomplete="current-password"')
            + ui.field("New password", "new", "", errors, "password", f"At least {req.db.int_setting('auth.min_password')} characters", True, 'autocomplete="new-password"')
            + ui.field("Repeat new password", "new2", "", errors, "password", required=True, extra='autocomplete="new-password"')
            + '<p><button>Change password</button></p></form></div>')


@route("GET", "/profile/password")
def pw_get(req):
    return page(req, "Change password", _pw_form(req))


@route("POST", "/profile/password")
def pw_post(req):
    cur, new, new2 = req.raw("current"), req.raw("new"), req.raw("new2")
    errors = {}
    if not auth.verify_password(cur, req.user["pw_hash"]):
        errors["current"] = "Current password is wrong"
    e = auth.password_error(req.db, new)
    if e:
        errors["new"] = e
    elif new == cur:
        errors["new"] = "Choose a password different from the current one"
    elif new != new2:
        errors["new2"] = "The two passwords do not match"
    if errors:
        return page(req, "Change password", _pw_form(req, errors), 400)
    with req.db.tx():
        req.db.x("UPDATE users SET pw_hash=?, must_change=0, version=version+1 WHERE id=?",
                 (auth.hash_password(new), req.user["id"]))
        auth.destroy_user_sessions(req.db, req.user["id"], req.session["token_hash"])
        req.db.audit(req.user, "user.password_changed", "self")
    return redirect(req, "/vendors", "ok", "Password changed.")
