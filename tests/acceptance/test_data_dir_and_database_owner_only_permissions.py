"""A fresh data directory is private: the directory is 0700, driftwatch.db and secret.key are 0600.

Expected: with a permissive umask (022) the data directory has no group/other bits and the database and secret key have none either
Source: the security review (SECURITY.md S5) and the README ("written readable by its owner only").
"""

import tempfile
from pathlib import Path
import os
from driftwatch import config
from driftwatch.db import Database


def test_fresh_data_dir_owner_only():
    base = Path(tempfile.mkdtemp())
    cfg = config.load(env={})
    cfg.data_dir = base / "data"
    old = os.umask(0o022)
    try:
        config.prepare_data_dir(cfg)
        db = Database(cfg.db_path)
        db.migrate()
        db.close()
    finally:
        os.umask(old)
    modes = {n: (p.stat().st_mode & 0o777) for n, p in
             (("data dir", cfg.data_dir), ("driftwatch.db", cfg.db_path), ("secret.key", cfg.data_dir / "secret.key"))}
    assert modes == {"data dir": 0o700, "driftwatch.db": 0o600, "secret.key": 0o600}, {k: oct(v) for k, v in modes.items()}
