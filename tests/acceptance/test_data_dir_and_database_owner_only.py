"""The data directory is private to its owner, and so are the database and the secret key.

Expected: on a fresh start under a permissive umask, the data directory is mode 0700 and
driftwatch.db and secret.key are 0600 (no group/other bits).
Source: issue #2 and the security review (SECURITY.md S5).
"""

import os
import tempfile
from pathlib import Path
from _helpers.driver import ROOT  # noqa: F401  (puts the repository on sys.path)

from driftwatch import config
from driftwatch.db import Database


def test_fresh_data_dir_db_and_key_private():
    base = Path(tempfile.mkdtemp())
    old = os.umask(0o022)
    try:
        cfg = config.load(env={})
        cfg.data_dir = base / "data"
        config.prepare_data_dir(cfg)
        db = Database(cfg.db_path)
        db.migrate()
        db.close()
    finally:
        os.umask(old)
    modes = {
        "data dir": (cfg.data_dir, 0o700),
        "driftwatch.db": (cfg.db_path, 0o600),
        "secret.key": (cfg.data_dir / "secret.key", 0o600),
    }
    for name, (path, want) in modes.items():
        got = path.stat().st_mode & 0o777
        assert got == want, f"{name} should be {oct(want)}, is {oct(got)}"
