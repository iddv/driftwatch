"""Small shared helpers: time, escaping, hashing."""
import hashlib
import html
import re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

_now_override = None


def now() -> datetime:
    return _now_override or datetime.now(timezone.utc).replace(microsecond=0)


def set_now(dt):
    """Test hook: pin the clock (None to release)."""
    global _now_override
    _now_override = dt


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    return iso(now())


def parse_dt(s):
    """Parse ISO-8601 / RFC 822 / date-only strings into aware UTC datetimes; None if impossible."""
    if not s:
        return None
    s = s.strip()
    dt = None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(s)
        except (TypeError, ValueError, IndexError):
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def esc(s) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def sha256(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def collapse_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def add_months(year: int, month: int, delta: int):
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
