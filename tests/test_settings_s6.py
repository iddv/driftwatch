import os
from unittest import mock

from driftwatch import scoring, util
from .helpers import AppCase, rss
from email.utils import format_datetime


class TrendCurrentMonth(AppCase):
    def _row(self, name):
        # one removal published now (current month), nothing else
        self.fixture(f"{name}.xml", rss([("1", "Thing removed", format_datetime(util.now()), "x")]))
        vid = self.add_vendor(name)
        self.add_source(vid, f"{name}.xml", "rss")
        return [r for r in scoring.churn_table(self.db, self.cfg)["rows"] if r["vendor"]["id"] == vid][0]

    def test_default_includes_current(self):
        r = self._row("S6a")
        self.assertEqual((r["recent"], r["trend"]), (5, "up"))

    def test_false_excludes_current(self):
        self.db.set_setting("churn.trend_includes_current_month", "false")
        self.addCleanup(self.db.set_setting, "churn.trend_includes_current_month", "true")
        r = self._row("S6b")
        self.assertEqual((r["recent"], r["trend"]), (0, "flat"))

    def test_env(self):
        with mock.patch.dict(os.environ, {"CHURN_TREND_INCLUDES_CURRENT_MONTH": "false"}):
            self.assertEqual(self._row("S6c")["recent"], 0)
