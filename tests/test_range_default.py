import datetime

from driftwatch import util
from .helpers import AppCase


class EvidenceDefaultRange(AppCase):
    def test_evidence_default_range(self):
        a = self.admin.post("/vendors/new", name="RenewA", category="other", renewal_date="2027-03-01")[1]["Location"]
        util.set_now(__import__("datetime").datetime(2026, 10, 10, 12, tzinfo=__import__("datetime").timezone.utc))
        self.addCleanup(util.set_now, None)
        b = self.add_vendor("RenewNone")
        fa = self.admin.get(a + "/evidence")[2]
        fb = self.admin.get(f"/vendors/{b}/evidence")[2]
        for v in ("2026-03-01", "2027-03-01"):
            self.assertIn(f'value="{v}"', fa)
        for v in ("2025-10-10", "2026-10-10"):
            self.assertIn(f'value="{v}"', fb)
