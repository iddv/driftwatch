"""Demo content.

Expected: 8 vendors, 16 sources covering every source type, history entries in mixed statuses, and 2 extra users (analyst and viewer) whose one-time passwords are printed; the load is recorded in the audit log
Source: "Contains 8 vendors across the categories ... 16 sources of every type, and about 150 entries over 18 months in mixed statuses, plus 2 extra users (analyst and viewer) whose one-time passwords are printed."
"""

from _helpers.driver import *

import subprocess, os, tempfile, sqlite3
def test_demo_content():
    d = tempfile.mkdtemp(); env = dict(os.environ, DRIFTWATCH_DATA_DIR=d)
    r = subprocess.run([str(ROOT / "bin" / "driftwatch"), "demo", "load"], env=env, capture_output=True, text=True, cwd=d)
    assert r.returncode == 0
    c = sqlite3.connect(d + "/driftwatch.db")
    assert c.execute("select count(*) from vendors").fetchone()[0] == 8
    assert c.execute("select count(*) from sources").fetchone()[0] == 16
    assert {r[0] for r in c.execute("select type from sources")} >= {"rss", "atom", "jsonfeed", "github", "html"}
    assert {r[0] for r in c.execute("select status from entries")} == {"unreviewed", "reviewed", "dismissed"}
    assert 100 <= c.execute("select count(*) from entries").fetchone()[0] <= 200
    assert {r[0] for r in c.execute("select role from users")} == {"analyst", "viewer"}
    assert r.stdout.count("one-time password") >= 2
    assert c.execute("select count(*) from audit where action like '%demo%'").fetchone()[0] >= 1
