"""Background scheduler: picks due sources and fetches them with bounded concurrency."""
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.parse import urlsplit

from . import ingest, util


class Scheduler:
    def __init__(self, db, cfg, tick=15):
        self.db, self.cfg, self.tick = db, cfg, tick
        self.stop_ev = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=max(1, cfg.fetch_concurrency), thread_name_prefix="fetch")
        self._host_locks = {}
        self._hl_guard = threading.Lock()
        self._inflight = set()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._loop, name="scheduler", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_ev.set()
        self.pool.shutdown(wait=False, cancel_futures=True)

    def _loop(self):
        while not self.stop_ev.is_set():
            try:
                self.run_due()
            except Exception:  # keep the scheduler alive
                pass
            self.stop_ev.wait(self.tick)

    def due_sources(self):
        now = util.now()
        out = []
        rows = self.db.q("SELECT s.* FROM sources s JOIN vendors v ON v.id=s.vendor_id "
                         "WHERE s.paused=0 AND v.archived=0")
        for s in rows:
            last = util.parse_dt(s["last_attempt_at"])
            if last is None or now - last >= timedelta(seconds=s["interval_s"]):
                out.append(s)
        return out

    def run_due(self):
        for s in self.due_sources():
            if s["id"] in self._inflight:
                continue
            self._inflight.add(s["id"])
            self.pool.submit(self._run, s)

    def _host_lock(self, url):
        host = urlsplit(url).netloc.lower()
        with self._hl_guard:
            return self._host_locks.setdefault(host, threading.Lock())

    def _run(self, s):
        try:
            lock = self._host_lock(s["url"])
            if not lock.acquire(blocking=False):
                return  # one fetch per host at a time; picked up again next tick
            try:
                ingest.run_fetch(self.db, self.cfg, s["id"])
            finally:
                lock.release()
        finally:
            self._inflight.discard(s["id"])
            self.db.close()
