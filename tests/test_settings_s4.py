import os
from datetime import timedelta
from email.utils import format_datetime
from unittest import mock

from driftwatch import scoring, util
from .helpers import AppCase, rss


class CountEdited(AppCase):
    def _total(self, name):
        now = format_datetime(util.now())
        self.fixture(f"{name}.xml", rss([("1", "Thing removed", now, "orig")]))
        vid = self.add_vendor(name)
        sid = self.add_source(vid, f"{name}.xml", "rss")
        self.fixture(f"{name}.xml", rss([("1", "Thing removed", now, "orig changed")]))
        self.admin.post(f"/sources/{sid}/fetch")
        self.assertEqual(self.db.val("SELECT COUNT(*) FROM entries WHERE source_id=? AND kind='edited'", (sid,)), 1)
        row = [r for r in scoring.churn_table(self.db, self.cfg)["rows"] if r["vendor"]["id"] == vid][0]
        return row["total"]

    def test_default_counts(self):
        self.assertEqual(self._total("S4a"), 10)  # removal 5 x2 unreviewed entries

    def test_false_excludes(self):
        self.db.set_setting("churn.count_edited", "false")
        self.addCleanup(self.db.set_setting, "churn.count_edited", "true")
        self.assertEqual(self._total("S4b"), 5)

    def test_env(self):
        with mock.patch.dict(os.environ, {"CHURN_COUNT_EDITED": "false"}):
            self.assertEqual(self._total("S4c"), 5)
