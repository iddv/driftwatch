import os
from unittest import mock

from driftwatch import util
from .helpers import AppCase, rss


class RestoreResumes(AppCase):
    def _cycle(self, name):
        self.fixture(f"{name}.xml", rss([("1", "x", "Mon, 01 Jan 2026 00:00:00 GMT", "y")]))
        vid = self.add_vendor(name)
        sid = self.add_source(vid, f"{name}.xml", "rss")
        ver = lambda: self.db.val("SELECT version FROM vendors WHERE id=?", (vid,))
        self.admin.post(f"/vendors/{vid}/archive", version=ver())
        self.admin.post(f"/vendors/{vid}/restore", version=ver())
        return self.db.val("SELECT paused FROM sources WHERE id=?", (sid,))

    def test_default_true_resumes(self):
        self.assertEqual(self.db.setting("vendors.restore_resumes_fetching"), "true")
        self.assertEqual(self._cycle("S1a"), 0)

    def test_false_leaves_paused(self):
        self.db.set_setting("vendors.restore_resumes_fetching", "false")
        self.addCleanup(self.db.set_setting, "vendors.restore_resumes_fetching", "true")
        self.assertEqual(self._cycle("S1b"), 1)

    def test_env_overrides(self):
        with mock.patch.dict(os.environ, {"VENDORS_RESTORE_RESUMES_FETCHING": "false"}):
            self.assertEqual(self._cycle("S1c"), 1)
