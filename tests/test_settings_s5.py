import os
import tempfile
import sqlite3
from pathlib import Path
from unittest import mock

from driftwatch import db as dbmod
from .helpers import AppCase


class NameCase(AppCase):
    def test_default_insensitive_refuses(self):
        self.add_vendor("CaseCo")
        s, h, b = self.admin.post("/vendors/new", name="caseco", category="other")
        self.assertEqual(s, 400)
        self.assertIn("A vendor with this name exists", b)

    def test_false_allows_distinct(self):
        self.db.set_setting("vendors.name_case_insensitive", "false")
        self.addCleanup(self.db.set_setting, "vendors.name_case_insensitive", "true")
        self.add_vendor("CaseTwo")
        self.add_vendor("casetwo")
        s, h, b = self.admin.post("/vendors/new", name="casetwo", category="other")
        self.assertEqual(s, 400)  # exact duplicate still refused

    def test_env(self):
        self.add_vendor("CaseThree")
        with mock.patch.dict(os.environ, {"VENDORS_NAME_CASE_INSENSITIVE": "false"}):
            self.add_vendor("casethree")

    def test_migration_from_v1_keeps_data(self):
        with tempfile.TemporaryDirectory() as t:
            path = Path(t) / "x.db"
            con = sqlite3.connect(path)
            for stmt in dbmod.SCHEMA_V1.split(";\n"):
                if stmt.strip():
                    con.execute(stmt)
            con.execute("INSERT INTO meta VALUES('schema_version','1')")
            con.execute("INSERT INTO vendors(name,category,created_at) VALUES('Old','other','2026-01-01T00:00:00Z')")
            con.commit(); con.close()
            d = dbmod.Database(path)
            d.migrate(backup_dir=Path(t) / "bk")
            self.assertEqual(d.val("SELECT name FROM vendors"), "Old")
            d.x("INSERT INTO vendors(name,category,created_at) VALUES('old','other','2026-01-01T00:00:00Z')")
            self.assertTrue(list((Path(t) / "bk").glob("pre-migration-v1-*")))
            d.close()
