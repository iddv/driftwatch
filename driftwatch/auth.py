"""Users, passwords, lockout and sessions."""
import base64
import hashlib
import hmac
import secrets
from datetime import timedelta

from . import util

ROLES = ["viewer", "analyst", "admin"]
RANK = {"viewer": 1, "analyst": 2, "admin": 3}
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt$%d$%d$%d$%s$%s" % (_N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(h).decode())


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, h = stored.split("$")
        calc = hashlib.scrypt(pw.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(h))
    except Exception:
        return False


def password_error(db, pw: str):
    n = db.int_setting("auth.min_password")
    if len(pw) < n:
        return f"Password must be at least {n} characters"
    return None


def one_time_password(db) -> str:
    return secrets.token_urlsafe(max(12, db.int_setting("auth.min_password")))


def valid_username(name: str):
    if not name or not name.strip():
        return "Username is required"
    if len(name) > 64 or not all(c.isalnum() or c in "._-@" for c in name):
        return "Use letters, digits and . _ - @ only (max 64 characters)"
    return None


def admin_exists(db) -> bool:
    return bool(db.val("SELECT 1 FROM users WHERE role='admin' LIMIT 1"))


def create_user(db, username, role, password, must_change=False):
    cur = db.x("INSERT INTO users(username,pw_hash,role,must_change,created_at) VALUES(?,?,?,?,?)",
               (username, hash_password(password), role, int(must_change), util.now_iso()))
    return cur.lastrowid


def active_admins(db) -> int:
    return db.val("SELECT COUNT(*) FROM users WHERE role='admin' AND active=1")


class AuthResult:
    def __init__(self, user=None, error=None):
        self.user, self.error = user, error


def authenticate(db, username, password) -> AuthResult:
    u = db.one("SELECT * FROM users WHERE username=?", (username.strip(),))
    generic = "Invalid username or password"
    if u is None:
        hash_password("x")  # keep timing similar
        db.audit(username.strip()[:64] or "?", "login.failed", "unknown user")
        return AuthResult(error=generic)
    now = util.now()
    if u["locked_until"] and util.parse_dt(u["locked_until"]) > now:
        db.audit(u, "login.blocked", "account locked")
        return AuthResult(error="Too many failed sign-ins. Account is locked until "
                          f"{u['locked_until'].replace('T', ' ').replace('Z', ' UTC')}.")
    if not verify_password(password, u["pw_hash"]):
        failed = u["failed_count"] + 1
        locked = None
        if failed >= db.int_setting("auth.max_failures"):
            locked = util.iso(now + timedelta(minutes=db.int_setting("auth.lockout_minutes")))
            failed = 0
        db.x("UPDATE users SET failed_count=?, locked_until=? WHERE id=?", (failed, locked, u["id"]))
        db.audit(u, "login.locked" if locked else "login.failed")
        if locked:
            return AuthResult(error="Too many failed sign-ins. Account is locked for "
                              f"{db.int_setting('auth.lockout_minutes')} minutes.")
        return AuthResult(error=generic)
    if not u["active"]:
        db.audit(u, "login.failed", "deactivated")
        return AuthResult(error=generic)
    db.x("UPDATE users SET failed_count=0, locked_until=NULL WHERE id=?", (u["id"],))
    db.audit(u, "login.success")
    return AuthResult(user=u)


def _th(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db, user_id) -> str:
    token = secrets.token_urlsafe(32)
    db.x("INSERT INTO sessions(token_hash,user_id,created_at,last_seen) VALUES(?,?,?,?)",
         (_th(token), user_id, util.now_iso(), util.now_iso()))
    return token


def lookup_session(db, token):
    """Return (user_row, session_row) or (None, None). Applies idle expiry and refreshes last_seen."""
    if not token:
        return None, None
    s = db.one("SELECT * FROM sessions WHERE token_hash=?", (_th(token),))
    if s is None:
        return None, None
    now = util.now()
    idle = timedelta(hours=db.int_setting("auth.session_idle_hours"))
    if now - util.parse_dt(s["last_seen"]) > idle:
        db.x("DELETE FROM sessions WHERE token_hash=?", (s["token_hash"],))
        return None, None
    u = db.one("SELECT * FROM users WHERE id=?", (s["user_id"],))
    if u is None or not u["active"]:
        db.x("DELETE FROM sessions WHERE token_hash=?", (s["token_hash"],))
        return None, None
    if (now - util.parse_dt(s["last_seen"])).total_seconds() > 30:
        db.x("UPDATE sessions SET last_seen=? WHERE token_hash=?", (util.iso(now), s["token_hash"]))
    return u, s


def destroy_session(db, token):
    if token:
        db.x("DELETE FROM sessions WHERE token_hash=?", (_th(token),))


def destroy_user_sessions(db, user_id, keep_hash=None):
    if keep_hash:
        db.x("DELETE FROM sessions WHERE user_id=? AND token_hash<>?", (user_id, keep_hash))
    else:
        db.x("DELETE FROM sessions WHERE user_id=?", (user_id,))


def csrf_token(secret: str, binding: str) -> str:
    return hmac.new(secret.encode(), b"csrf|" + binding.encode(), hashlib.sha256).hexdigest()
