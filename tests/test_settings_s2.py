import datetime
import os
from unittest import mock

from driftwatch import evidence, util
from .helpers import AppCase, rss


class RangeBasis(AppCase):
    def _setup(self, name):
        self.fixture(f"{name}.xml", rss([("1", "old post", "Mon, 01 Jan 2024 00:00:00 GMT", "text")]))
        vid = self.add_vendor(name)
        self.add_source(vid, f"{name}.xml", "rss")
        return vid

    def _count(self, vid, d1, d2):
        v = self.db.one("SELECT * FROM vendors WHERE id=?", (vid,))
        return len(evidence.select_entries(self.db, self.cfg, vid, d1, d2))

    def test_published_default(self):
        vid = self._setup("S2a")
        self.assertEqual(self.db.setting("export.range_basis"), "published")
        self.assertEqual(self._count(vid, datetime.date(2024, 1, 1), datetime.date(2024, 1, 2)), 1)
        today = util.now().date()
        self.assertEqual(self._count(vid, today - datetime.timedelta(days=1), today + datetime.timedelta(days=1)), 0)

    def test_detected(self):
        vid = self._setup("S2b")
        self.db.set_setting("export.range_basis", "detected")
        self.addCleanup(self.db.set_setting, "export.range_basis", "published")
        self.assertEqual(self._count(vid, datetime.date(2024, 1, 1), datetime.date(2024, 1, 2)), 0)
        today = util.now().date()
        self.assertEqual(self._count(vid, today - datetime.timedelta(days=1), today + datetime.timedelta(days=1)), 1)

    def test_env(self):
        vid = self._setup("S2c")
        with mock.patch.dict(os.environ, {"EXPORT_RANGE_BASIS": "detected"}):
            self.assertEqual(self._count(vid, datetime.date(2024, 1, 1), datetime.date(2024, 1, 2)), 0)
