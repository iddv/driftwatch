"""SQLite storage: schema, migrations, settings, audit log."""
import json
import os
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from . import util

SCHEMA_VERSION = 2

SCHEMA_V1 = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE users (
  id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, pw_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('viewer','analyst','admin')), active INTEGER NOT NULL DEFAULT 1,
  must_change INTEGER NOT NULL DEFAULT 0, failed_count INTEGER NOT NULL DEFAULT 0, locked_until TEXT,
  created_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
CREATE TABLE sessions (
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
  last_seen TEXT NOT NULL, flash TEXT);
CREATE TABLE audit (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, user_id INTEGER, username TEXT, action TEXT NOT NULL, detail TEXT);
CREATE INDEX audit_ts ON audit(ts);
CREATE TABLE vendors (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, category TEXT NOT NULL, homepage TEXT,
  renewal_date TEXT, notes TEXT, archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1, updated_by TEXT, updated_at TEXT);
CREATE TABLE sources (
  id INTEGER PRIMARY KEY, vendor_id INTEGER NOT NULL REFERENCES vendors(id), url TEXT NOT NULL, type TEXT NOT NULL,
  selector TEXT, interval_s INTEGER NOT NULL, paused INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0,
  failing INTEGER NOT NULL DEFAULT 0, baseline_done INTEGER NOT NULL DEFAULT 0, last_attempt_at TEXT,
  last_fetch_at TEXT, last_result TEXT, last_new INTEGER NOT NULL DEFAULT 0, lock_at TEXT,
  created_at TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1, updated_by TEXT, updated_at TEXT,
  UNIQUE (vendor_id, url));
CREATE TABLE fetch_log (
  id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id), ts TEXT NOT NULL, result TEXT NOT NULL,
  detail TEXT, http_status INTEGER, new_entries INTEGER NOT NULL DEFAULT 0, snapshot_id INTEGER);
CREATE INDEX fetch_log_src ON fetch_log(source_id, id);
CREATE TABLE snapshots (
  id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id), fetched_at TEXT NOT NULL,
  http_status INTEGER, sha256 TEXT NOT NULL, content_type TEXT, size INTEGER NOT NULL, body BLOB NOT NULL,
  parse_ok INTEGER NOT NULL DEFAULT 1, selector TEXT, extract TEXT);
CREATE INDEX snapshots_src ON snapshots(source_id, id);
CREATE TABLE entries (
  id INTEGER PRIMARY KEY, source_id INTEGER NOT NULL REFERENCES sources(id), vendor_id INTEGER NOT NULL REFERENCES vendors(id),
  snapshot_id INTEGER NOT NULL REFERENCES snapshots(id), dedup_key TEXT NOT NULL, text_hash TEXT NOT NULL,
  kind TEXT NOT NULL, backfill INTEGER NOT NULL DEFAULT 0, title TEXT, published_at TEXT, link TEXT,
  text_after TEXT, text_before TEXT, detected_at TEXT NOT NULL, eff_at TEXT NOT NULL, edit_of INTEGER,
  suggested_category TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'unreviewed', category TEXT, impact TEXT, note TEXT,
  affects_us INTEGER NOT NULL DEFAULT 0, dismiss_reason TEXT, reviewed_by TEXT, reviewed_at TEXT,
  version INTEGER NOT NULL DEFAULT 1, updated_by TEXT, updated_at TEXT,
  UNIQUE (source_id, dedup_key, text_hash));
CREATE INDEX entries_vendor ON entries(vendor_id, eff_at);
CREATE INDEX entries_status ON entries(status, eff_at);
CREATE TABLE entry_history (
  id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES entries(id), ts TEXT NOT NULL, username TEXT,
  action TEXT NOT NULL, detail TEXT);
CREATE INDEX entry_history_e ON entry_history(entry_id);
CREATE TABLE keyword_rules (id INTEGER PRIMARY KEY, category TEXT NOT NULL, keyword TEXT NOT NULL, ord INTEGER NOT NULL);
CREATE TABLE exports (
  id INTEGER PRIMARY KEY, vendor_id INTEGER NOT NULL REFERENCES vendors(id), username TEXT, ts TEXT NOT NULL,
  range_from TEXT, range_to TEXT, min_impact TEXT, categories TEXT, entry_count INTEGER, manifest_hash TEXT,
  filename TEXT, size INTEGER);
"""

# v2: vendor-name uniqueness becomes case-sensitive at the database level; case-insensitivity is an app-level setting
SCHEMA_V2 = [
    """CREATE TABLE vendors_new (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, category TEXT NOT NULL, homepage TEXT,
  renewal_date TEXT, notes TEXT, archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1, updated_by TEXT, updated_at TEXT)""",
    "INSERT INTO vendors_new SELECT id,name,category,homepage,renewal_date,notes,archived,created_at,version,updated_by,updated_at FROM vendors",
    "DROP TABLE vendors",
    "ALTER TABLE vendors_new RENAME TO vendors",
]

CATEGORIES = ["breaking change", "removal", "deprecation", "default change", "scope narrowing", "security",
              "new capability", "fix", "other"]
BEHAVIOR_SHIFTS = ["breaking change", "removal", "deprecation", "default change", "scope narrowing", "security"]
VENDOR_CATEGORIES = ["database", "identity", "secrets", "cloud infrastructure", "observability", "payments", "other"]
IMPACTS = ["low", "medium", "high"]
SOURCE_TYPES = ["auto", "rss", "atom", "jsonfeed", "github", "html"]
SOURCE_TYPE_LABELS = {"auto": "Auto-detect", "rss": "RSS", "atom": "Atom", "jsonfeed": "JSON Feed",
                      "github": "GitHub releases", "html": "HTML page"}

DEFAULT_KEYWORDS = [
    ("deprecation", ["deprecat", "sunset", "end of life", "EOL"]),
    ("removal", ["removed", "no longer", "discontinued"]),
    ("breaking change", ["breaking", "incompatible"]),
    ("default change", ["default", "now requires", "now enabled"]),
    ("scope narrowing", ["limit", "quota", "only available", "restricted", "no longer supported in"]),
    ("security", ["CVE", "vulnerability", "security"]),
]

# key -> (default, kind, label, choices/min/max)
SETTINGS = {
    "triage.suggestions": ("suggest_only", "choice", "Keyword suggestions", ["suggest_only", "auto_apply"]),
    "fetch.robots_txt": ("respect", "choice", "robots.txt", ["respect", "ignore"]),
    "churn.count_basis": ("include_unreviewed", "choice", "Churn counts", ["include_unreviewed", "confirmed_only"]),
    "export.include_dismissed": ("no", "choice", "Include dismissed in evidence packs", ["no", "yes"]),
    "vendors.allow_purge": ("no", "choice", "Allow purging archived vendors", ["no", "yes"]),
    "fetch.default_interval_minutes": ("360", "int", "Default fetch interval (minutes, 15-10080)", (15, 10080)),
    "fetch.failure_threshold": ("3", "int", "Failures before a source is marked failing", (1, 100)),
    "diff.noise_chars": ("20", "int", "Ignore HTML changes shorter than (characters)", (0, 10000)),
    "export.max_mb": ("200", "int", "Evidence pack size limit (MB)", (1, 100000)),
    "auth.min_password": ("12", "int", "Minimum password length", (8, 128)),
    "auth.max_failures": ("5", "int", "Failed sign-ins before lockout", (1, 1000)),
    "auth.lockout_minutes": ("15", "int", "Lockout duration (minutes)", (1, 100000)),
    "auth.session_idle_hours": ("12", "int", "Session idle expiry (hours)", (1, 8760)),
    "vendors.restore_resumes_fetching": ("true", "choice", "Restoring a vendor resumes fetching", ["true", "false"]),
    "export.range_basis": ("published", "choice", "Evidence range basis", ['published', 'detected']),
    "fetch.robots_block_fails_immediately": ("true", "choice", "robots.txt block marks source failing immediately", ['true', 'false']),
    "churn.count_edited": ("true", "choice", "Edited entries count toward churn", ['true', 'false']),
    "churn.trend_includes_current_month": ("true", "choice", "Trend includes the current month", ['true', 'false']),
    "vendors.name_case_insensitive": ("true", "choice", "Vendor names are case-insensitive", ['true', 'false']),
    "weight.breaking change": ("5", "int", "Weight: breaking change", (0, 100)),
    "weight.removal": ("5", "int", "Weight: removal", (0, 100)),
    "weight.scope narrowing": ("4", "int", "Weight: scope narrowing", (0, 100)),
    "weight.deprecation": ("3", "int", "Weight: deprecation", (0, 100)),
    "weight.default change": ("3", "int", "Weight: default change", (0, 100)),
    "weight.security": ("2", "int", "Weight: security", (0, 100)),
    "weight.new capability": ("0", "int", "Weight: new capability", (0, 100)),
    "weight.fix": ("0", "int", "Weight: fix", (0, 100)),
    "weight.other": ("0", "int", "Weight: other", (0, 100)),
    "impact.low": ("1", "int", "Multiplier: low impact", (0, 100)),
    "impact.medium": ("2", "int", "Multiplier: medium impact", (0, 100)),
    "impact.high": ("3", "int", "Multiplier: high impact", (0, 100)),
}


def env_name(key):
    """Environment variable that overrides a setting, e.g. vendors.restore_resumes_fetching -> VENDORS_RESTORE_RESUMES_FETCHING."""
    return key.upper().replace(".", "_")


# settings whose value an environment variable may force everywhere
ENV_OVERRIDABLE = {"vendors.name_case_insensitive", "churn.trend_includes_current_month", "churn.count_edited", "fetch.robots_block_fails_immediately", "export.range_basis", "vendors.restore_resumes_fetching"}


class Database:
    def __init__(self, path):
        self.path = str(path)
        self._local = threading.local()

    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA foreign_keys=ON")
            c.execute("PRAGMA busy_timeout=30000")
            self._local.conn = c
        return c

    def close(self):
        c = getattr(self._local, "conn", None)
        if c:
            c.close()
            self._local.conn = None

    def q(self, sql, args=()):
        return self.conn.execute(sql, args).fetchall()

    def one(self, sql, args=()):
        return self.conn.execute(sql, args).fetchone()

    def x(self, sql, args=()):
        return self.conn.execute(sql, args)

    def val(self, sql, args=()):
        r = self.conn.execute(sql, args).fetchone()
        return r[0] if r else None

    @contextmanager
    def tx(self):
        c = self.conn
        if c.in_transaction:
            yield c
            return
        c.execute("BEGIN IMMEDIATE")
        try:
            yield c
        except BaseException:
            c.execute("ROLLBACK")
            raise
        else:
            c.execute("COMMIT")

    # ---- migrations -------------------------------------------------
    def migrate(self, backup_dir=None):
        c = self.conn
        has_meta = c.execute("SELECT 1 FROM sqlite_master WHERE name='meta'").fetchone()
        current = 0
        if has_meta:
            current = int(self.val("SELECT value FROM meta WHERE key='schema_version'") or 0)
        if current >= SCHEMA_VERSION:
            return
        if current > 0 and backup_dir:
            Path(backup_dir).mkdir(parents=True, exist_ok=True)
            dest = Path(backup_dir) / f"pre-migration-v{current}-{util.now().strftime('%Y%m%dT%H%M%S')}.db"
            self.backup_to(dest)
        c.execute("PRAGMA foreign_keys=OFF")  # table rebuild; cannot be changed inside a transaction
        with self.tx():
            if current < 1:
                for stmt in SCHEMA_V1.split(";\n"):
                    if stmt.strip():
                        c.execute(stmt)
                self._seed_keywords()
            if current < 2:
                for stmt in SCHEMA_V2:
                    c.execute(stmt)
            c.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)", (str(SCHEMA_VERSION),))
        c.execute("PRAGMA foreign_keys=ON")

    def _seed_keywords(self):
        n = 0
        for cat, kws in DEFAULT_KEYWORDS:
            for kw in kws:
                self.x("INSERT INTO keyword_rules(category,keyword,ord) VALUES(?,?,?)", (cat, kw, n))
                n += 1

    def backup_to(self, dest):
        dst = sqlite3.connect(str(dest))
        try:
            self.conn.backup(dst)
        finally:
            dst.close()

    # ---- settings ---------------------------------------------------
    def setting(self, key):
        if key in ENV_OVERRIDABLE:
            ev = os.environ.get(env_name(key))
            if ev is not None and ev.strip().lower() in SETTINGS[key][3]:
                return ev.strip().lower()
        r = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return r[0] if r else SETTINGS[key][0]

    def int_setting(self, key):
        return int(self.setting(key))

    def all_settings(self):
        return {k: self.setting(k) for k in SETTINGS}

    def set_setting(self, key, value):
        self.x("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (key, str(value)))

    # ---- audit ------------------------------------------------------
    def audit(self, user, action, detail=None):
        if isinstance(user, str):
            uid, uname = None, user
        else:
            uid = user["id"] if user else None
            uname = user["username"] if user else None
        if detail is not None and not isinstance(detail, str):
            detail = json.dumps(detail, sort_keys=True)
        self.x("INSERT INTO audit(ts,user_id,username,action,detail) VALUES(?,?,?,?,?)",
               (util.now_iso(), uid, uname, action, detail))
