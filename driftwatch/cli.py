"""Command line entry point: serve, demo load, backup, restore, test."""
import argparse
import fcntl
import io
import json
import os
import shutil
import signal
import sqlite3
import sys
import tarfile
import tempfile
import threading
from pathlib import Path

from . import __version__, config, demo, util
from .db import Database
from .scheduler import Scheduler


def _open(cfg, migrate=True):
    config.prepare_data_dir(cfg)
    db = Database(cfg.db_path)
    if migrate:
        db.migrate(backup_dir=cfg.data_dir / "backups")
    return db


def _lock(cfg):
    fh = open(Path(cfg.data_dir) / "driftwatch.lock", "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def cmd_serve(args, cfg):
    from . import web
    config.prepare_data_dir(cfg)
    lock = _lock(cfg)
    if lock is None:
        raise SystemExit(f"Another Driftwatch instance is already using the data directory {cfg.data_dir}.")
    db = _open(cfg)
    app = web.App(db, cfg)
    srv = web.make_server(app, cfg)
    sched = Scheduler(db, cfg)
    app.scheduler = sched
    sched.start()
    print(f"Driftwatch {__version__} listening on http://{cfg.host}:{cfg.port}  (data: {cfg.data_dir})", flush=True)
    if not _has_admin(db):
        print(f"No admin exists yet: open http://{cfg.host}:{cfg.port}/setup to create one.", flush=True)
    signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=srv.shutdown, daemon=True).start())
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        sched.stop()
        srv.server_close()
    return 0


def _has_admin(db):
    from . import auth
    return auth.admin_exists(db)


def cmd_demo(args, cfg):
    db = _open(cfg)
    try:
        created, otps = demo.load(db, cfg, force_into_existing=args.force_into_existing)
    except demo.DemoError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Loaded demo data: {created['vendors']} vendors, {created['sources']} sources, {created['entries']} entries.")
    print(f"Demo sources point at fixture files served locally by Driftwatch at {cfg.base_url}/_fixtures/ "
          "(the service must run on that address for fetches to work).")
    for u, p in otps.items():
        print(f"  user {u}: one-time password {p}  (must be changed at first sign-in)")
    print("Reload the Vendors page to see it.")
    return 0


def cmd_backup(args, cfg):
    if not cfg.db_path.exists():
        print(f"error: no database at {cfg.db_path}", file=sys.stderr)
        return 1
    db = Database(cfg.db_path)
    db.audit("cli", "backup", {"file": os.path.basename(args.file)})
    out = Path(args.file)
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "driftwatch.db"
        db.backup_to(snap)  # consistent even while the service is running
        tmp_tar = out.with_name(out.name + ".partial")
        with tarfile.open(tmp_tar, "w:gz") as tf:
            tf.add(snap, "driftwatch.db")
            for sub in ("fixtures", "exports"):
                if (cfg.data_dir / sub).is_dir():
                    tf.add(cfg.data_dir / sub, sub)
            if (cfg.data_dir / "secret.key").exists():
                tf.add(cfg.data_dir / "secret.key", "secret.key")
            meta = json.dumps({"driftwatch": __version__, "created": util.now_iso()}).encode()
            ti = tarfile.TarInfo("backup.json")
            ti.size = len(meta)
            tf.addfile(ti, io.BytesIO(meta))
        os.replace(tmp_tar, out)
    print(f"Backup written to {out} ({out.stat().st_size} bytes)")
    return 0


def cmd_restore(args, cfg):
    src = Path(args.file)
    if not src.is_file():
        print(f"error: {src} not found", file=sys.stderr)
        return 1
    config.prepare_data_dir(cfg)
    lock = _lock(cfg)
    if lock is None:
        print("error: Driftwatch is running on this data directory. Stop it before restoring.", file=sys.stderr)
        return 1
    try:
        with tarfile.open(src, "r:gz") as tf:
            names = tf.getnames()
            if "driftwatch.db" not in names or "backup.json" not in names:
                print("error: this is not a Driftwatch backup", file=sys.stderr)
                return 1
            if cfg.db_path.exists() and not args.force:
                print(f"error: {cfg.db_path} already exists; use --force to replace it (the old database is kept as .pre-restore).",
                      file=sys.stderr)
                return 1
            with tempfile.TemporaryDirectory(dir=cfg.data_dir) as tmp:
                tf.extractall(tmp, filter="data")
                test = sqlite3.connect(Path(tmp) / "driftwatch.db")
                ok = test.execute("PRAGMA integrity_check").fetchone()[0]
                test.close()
                if ok != "ok":
                    print(f"error: backup database failed integrity check: {ok}", file=sys.stderr)
                    return 1
                stamp = util.now().strftime("%Y%m%dT%H%M%S")
                if cfg.db_path.exists():
                    shutil.move(cfg.db_path, str(cfg.db_path) + f".pre-restore-{stamp}")
                for ext in ("-wal", "-shm"):
                    Path(str(cfg.db_path) + ext).unlink(missing_ok=True)
                shutil.move(Path(tmp) / "driftwatch.db", cfg.db_path)
                for sub in ("fixtures", "exports"):
                    if (Path(tmp) / sub).is_dir():
                        shutil.copytree(Path(tmp) / sub, cfg.data_dir / sub, dirs_exist_ok=True)
                if (Path(tmp) / "secret.key").exists() and not os.environ.get("DRIFTWATCH_SESSION_SECRET"):
                    shutil.copy(Path(tmp) / "secret.key", cfg.data_dir / "secret.key")
        db = Database(cfg.db_path)
        db.migrate(backup_dir=cfg.data_dir / "backups")
        db.audit("cli", "restore", {"file": src.name})
    finally:
        lock.close()
    print(f"Restored {src} into {cfg.data_dir}")
    return 0


def cmd_test(args, cfg):
    import unittest
    root = Path(__file__).resolve().parent.parent
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), top_level_dir=str(root))
    res = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if res.wasSuccessful() else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="driftwatch", description="Track vendor changelog drift.")
    ap.add_argument("--version", action="version", version=f"driftwatch {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("serve", help="run the web service (default)")
    d = sub.add_parser("demo", help="demo data")
    dsub = d.add_subparsers(dest="demo_cmd", required=True)
    dl = dsub.add_parser("load", help="load demo vendors, sources and history")
    dl.add_argument("--force-into-existing", action="store_true")
    b = sub.add_parser("backup", help="write a consistent backup archive")
    b.add_argument("file")
    r = sub.add_parser("restore", help="restore a backup into a stopped instance")
    r.add_argument("file")
    r.add_argument("--force", action="store_true", help="replace an existing database")
    sub.add_parser("test", help="run the automated tests")
    args = ap.parse_args(argv)
    try:
        cfg = config.load()
        cmd = args.cmd or "serve"
        fn = {"serve": cmd_serve, "backup": cmd_backup, "restore": cmd_restore, "test": cmd_test}.get(cmd)
        if cmd == "demo":
            fn = cmd_demo
        return fn(args, cfg)
    except config.ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
