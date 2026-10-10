import csv
import hashlib
import io
import json
import re
import tarfile
import tempfile
import threading
import unittest
import zipfile
from datetime import timedelta
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from driftwatch import auth, cli, config, demo, util
from driftwatch.db import Database
from .helpers import AppCase, Client, rss


def rfc(dt):
    return format_datetime(dt)


def entries_of(db, source_id):
    return db.q("SELECT * FROM entries WHERE source_id=? ORDER BY id", (source_id,))


class FetchAndTriage(AppCase):
    def test_feed_baseline_new_item_edit_and_dedup(self):
        old = util.now() - timedelta(days=40)
        items = [("a1", "Old release", rfc(old), "Nothing special"), ("a2", "Second", rfc(old), "More text")]
        self.fixture("f1.xml", rss(items))
        vid = self.add_vendor("Feedco")
        sid = self.add_source(vid, "f1.xml", "rss")
        es = entries_of(self.db, sid)
        self.assertEqual(len(es), 2)
        self.assertTrue(all(e["backfill"] == 1 for e in es))
        self.assertTrue(all(e["status"] == "unreviewed" for e in es))
        # a new item appears
        items.append(("a3", "Sunset of the v1 API", rfc(util.now()), "The v1 API is deprecated."))
        self.fixture("f1.xml", rss(items))
        s, h, b = self.admin.post(f"/sources/{sid}/fetch")
        self.assertEqual(s, 303)
        es = entries_of(self.db, sid)
        self.assertEqual(len(es), 3)
        new = es[-1]
        self.assertEqual((new["backfill"], new["status"], new["suggested_category"]), (0, "unreviewed", "deprecation"))
        # fetching again: unchanged content, no snapshot duplicate, no entry
        n_snap = self.db.val("SELECT COUNT(*) FROM snapshots WHERE source_id=?", (sid,))
        self.admin.post(f"/sources/{sid}/fetch")
        self.assertEqual(self.db.val("SELECT COUNT(*) FROM snapshots WHERE source_id=?", (sid,)), n_snap)
        self.assertEqual(len(entries_of(self.db, sid)), 3)
        self.assertEqual(self.db.one("SELECT result FROM fetch_log WHERE source_id=? ORDER BY id DESC", (sid,))[0], "no change")
        # same key, changed text => new 'edited' entry linked to the original
        items[2] = ("a3", "Sunset of the v1 API", rfc(util.now()), "The v1 API is deprecated. Date moved.")
        self.fixture("f1.xml", rss(items))
        self.admin.post(f"/sources/{sid}/fetch")
        es = entries_of(self.db, sid)
        self.assertEqual(len(es), 4)
        self.assertEqual((es[3]["kind"], es[3]["edit_of"]), ("edited", new["id"]))
        # original text is never modified
        self.assertEqual(self.db.val("SELECT text_after FROM entries WHERE id=?", (new["id"],)), "The v1 API is deprecated.")

    def test_atom_json_github_sources(self):
        now = util.iso(util.now() - timedelta(days=3))
        self.fixture("a.xml", f'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>x1</id><title>Breaking change</title><updated>{now}</updated><content>Incompatible update</content></entry></feed>')
        self.fixture("j.json", json.dumps({"version": "https://jsonfeed.org/version/1", "items": [{"id": "1", "title": "Default is now enabled", "content_text": "t", "date_published": now}]}))
        vid = self.add_vendor("Multi")
        for name, t in (("a.xml", "atom"), ("j.json", "jsonfeed"), ("a.xml", "github")):
            url = self.fixture_url(name) + ("?gh=1" if t == "github" else "")
            sid = self.add_source(vid, name, t, url=url)
            self.assertEqual(len(entries_of(self.db, sid)), 1, t)

    def test_html_page_diff(self):
        page = lambda *bl: "<html><body><nav>menu</nav><div id='log'>" + "".join(f"<p>{b}</p>" for b in bl) + "</div></body></html>"
        base = ["Connections per instance are capped at 100 for everyone.", "Static paragraph that never changes at all."]
        self.fixture("p.html", page(*base))
        vid = self.add_vendor("Pagey")
        sid = self.add_source(vid, "p.html", "html", selector="#log")
        self.assertEqual(len(entries_of(self.db, sid)), 0)  # first snapshot is the baseline
        self.fixture("p.html", page("Connections per instance are limited to 50 on the standard plan now.", base[1], "A brand new announcement paragraph."))
        self.admin.post(f"/sources/{sid}/fetch")
        es = entries_of(self.db, sid)
        self.assertEqual(sorted(e["kind"] for e in es), ["added", "modified"])
        mod = [e for e in es if e["kind"] == "modified"][0]
        self.assertEqual(mod["text_before"], base[0])
        self.assertIn("limited to 50", mod["text_after"])
        self.assertEqual(mod["suggested_category"], "scope narrowing")
        # a typo-sized change is noise: kept in the snapshot, but no entry
        self.fixture("p.html", page("Connections per instance are limited to 50 on the standard plan now!", base[1], "A brand new announcement paragraph."))
        self.admin.post(f"/sources/{sid}/fetch")
        self.assertEqual(len(entries_of(self.db, sid)), 2)
        self.assertEqual(self.db.val("SELECT COUNT(*) FROM snapshots WHERE source_id=?", (sid,)), 3)

    def test_parse_error_keeps_raw_body_and_failing_after_three(self):
        self.fixture("bad.xml", "<html>not a feed")
        vid = self.add_vendor("Broken")
        s, h, b = self.admin.post(f"/vendors/{vid}/sources/new", url=self.fixture_url("bad.xml"), type="rss", interval_min="360")
        self.assertEqual(s, 200)
        self.assertIn("Test fetch failed", b)
        s, h, b = self.admin.post(f"/vendors/{vid}/sources/new", url=self.fixture_url("bad.xml"), type="rss", interval_min="360", save_anyway="1")
        sid = int(h["Location"].rsplit("/", 1)[1])
        snap = self.db.one("SELECT * FROM snapshots WHERE source_id=?", (sid,))
        self.assertEqual(snap["parse_ok"], 0)
        self.assertEqual(bytes(snap["body"]), b"<html>not a feed")
        self.assertEqual(len(entries_of(self.db, sid)), 0)
        for _ in range(2):
            self.admin.post(f"/sources/{sid}/fetch")
        self.assertEqual(self.db.val("SELECT failing FROM sources WHERE id=?", (sid,)), 1)
        self.assertIn("failing", self.admin.get("/vendors")[2])

    def test_unreachable_source_marked_failing(self):
        self.allow_loopback()
        vid = self.add_vendor("Deadhost")
        s, h, b = self.admin.post(f"/vendors/{vid}/sources/new", url="http://127.0.0.1:1/feed.xml", type="rss", interval_min="15", save_anyway="1")
        sid = int(h["Location"].rsplit("/", 1)[1])
        self.assertEqual(self.db.val("SELECT failing FROM sources WHERE id=?", (sid,)), 0)  # 1 failure so far (baseline)
        self.admin.post(f"/sources/{sid}/fetch")
        self.assertEqual(self.db.val("SELECT failing FROM sources WHERE id=?", (sid,)), 0)
        self.admin.post(f"/sources/{sid}/fetch")
        self.assertEqual(self.db.val("SELECT failing FROM sources WHERE id=?", (sid,)), 1)
        self.assertIn("connection failed", self.admin.get(f"/sources/{sid}")[2])

    def test_lock_prevents_double_fetch_and_recovers_when_stale(self):
        self.fixture("l.xml", rss([("1", "x", rfc(util.now()), "y")]))
        vid = self.add_vendor("Locky")
        sid = self.add_source(vid, "l.xml", "rss")
        self.db.x("UPDATE sources SET lock_at=? WHERE id=?", (util.now_iso(), sid))
        s, h, b = self.admin.post(f"/sources/{sid}/fetch")
        self.assertIn("Already fetching", self.admin.get(f"/sources/{sid}")[2])
        self.db.x("UPDATE sources SET lock_at=? WHERE id=?", (util.iso(util.now() - timedelta(minutes=11)), sid))
        self.admin.post(f"/sources/{sid}/fetch")
        self.assertIsNone(self.db.val("SELECT lock_at FROM sources WHERE id=?", (sid,)))
        self.assertEqual(self.db.val("SELECT result FROM fetch_log WHERE source_id=? ORDER BY id DESC", (sid,)), "no change")

    def test_robots_txt_respected(self):
        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/robots.txt":
                    body = b"User-agent: *\nDisallow: /"
                else:
                    body = rss([("1", "x", rfc(util.now()), "y")]).encode()
                self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            def log_message(self, *a): pass
        self.allow_loopback()
        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.shutdown)
        url = f"http://127.0.0.1:{srv.server_address[1]}/feed.xml"
        vid = self.add_vendor("Robotty")
        s, h, b = self.admin.post(f"/vendors/{vid}/sources/new", url=url, type="rss", interval_min="60", save_anyway="1")
        sid = int(h["Location"].rsplit("/", 1)[1])
        row = self.db.one("SELECT * FROM sources WHERE id=?", (sid,))
        self.assertEqual(row["failing"], 1)
        self.assertIn("blocked by robots.txt", row["last_result"])
        self.db.set_setting("fetch.robots_txt", "ignore")
        self.addCleanup(self.db.set_setting, "fetch.robots_txt", "respect")
        self.admin.post(f"/sources/{sid}/fetch")
        self.assertEqual(len(entries_of(self.db, sid)), 1)

    def test_triage_flow_history_and_stale_version(self):
        self.fixture("t.xml", rss([(f"g{i}", f"Item {i} removed", rfc(util.now()), "body") for i in range(4)]))
        vid = self.add_vendor("Triagey")
        sid = self.add_source(vid, "t.xml", "rss")
        ids = [e["id"] for e in entries_of(self.db, sid)]
        ver = lambda i: self.db.val("SELECT version FROM entries WHERE id=?", (i,))
        # high impact needs a note
        s, h, b = self.admin.post(f"/entries/{ids[0]}/triage", category="removal", impact="high", note="", version=ver(ids[0]))
        self.assertEqual(s, 400)
        self.assertIn("A note is required for high impact", b)
        self.assertEqual(self.db.val("SELECT status FROM entries WHERE id=?", (ids[0],)), "unreviewed")
        v0 = ver(ids[0])
        s, h, b = self.admin.post(f"/entries/{ids[0]}/triage", category="removal", impact="high", note="we use it", version=v0, affects_us="1")
        self.assertEqual(s, 303)
        e = self.db.one("SELECT * FROM entries WHERE id=?", (ids[0],))
        self.assertEqual((e["status"], e["category"], e["impact"], e["affects_us"], e["reviewed_by"]), ("reviewed", "removal", "high", 1, "root"))
        # a second save with the stale version is rejected and overwrites nothing
        s, h, b = self.admin.post(f"/entries/{ids[0]}/triage", category="fix", impact="low", note="", version=v0)
        self.assertEqual(s, 303)
        self.assertIn("Changed by root at", self.admin.get(h["Location"])[2])
        self.assertEqual(self.db.val("SELECT category FROM entries WHERE id=?", (ids[0],)), "removal")
        # dismiss, reopen
        self.admin.post(f"/entries/{ids[1]}/dismiss", reason="noise", version=ver(ids[1]))
        self.assertEqual(self.db.val("SELECT status FROM entries WHERE id=?", (ids[1],)), "dismissed")
        self.admin.post(f"/entries/{ids[1]}/reopen", version=ver(ids[1]))
        self.assertEqual(self.db.val("SELECT status FROM entries WHERE id=?", (ids[1],)), "unreviewed")
        actions = [r[0] for r in self.db.q("SELECT action FROM entry_history WHERE entry_id=? ORDER BY id", (ids[1],))]
        self.assertEqual(actions, ["detected", "dismissed", "reopened"])
        self.assertIn("reopened", self.admin.get(f"/entries/{ids[1]}")[2])
        # bulk: classify two entries, one of which is stale
        sel = [f"{ids[2]}:{ver(ids[2])}", f"{ids[3]}:{ver(ids[3]) - 1 or 99}"]
        s, h, b = self.admin.post("/triage/bulk", sel=sel, action="classify", category="deprecation", impact="medium", note="")
        self.assertEqual(self.db.val("SELECT category FROM entries WHERE id=?", (ids[2],)), "deprecation")
        self.assertEqual(self.db.val("SELECT status FROM entries WHERE id=?", (ids[3],)), "unreviewed")
        s, h, b = self.admin.post("/triage/bulk", sel=[f"{ids[3]}:{ver(ids[3])}"], action="dismiss", reason="")
        self.assertEqual(self.db.val("SELECT status FROM entries WHERE id=?", (ids[3],)), "dismissed")

    def test_auto_apply_setting(self):
        self.db.set_setting("triage.suggestions", "auto_apply")
        self.addCleanup(self.db.set_setting, "triage.suggestions", "suggest_only")
        self.fixture("auto.xml", rss([("1", "Feature removed", rfc(util.now()), "x"), ("2", "Just news", rfc(util.now()), "y")]))
        sid = self.add_source(self.add_vendor("Autoco"), "auto.xml", "rss")
        es = {e["dedup_key"]: e for e in entries_of(self.db, sid)}
        self.assertEqual((es["1"]["status"], es["1"]["impact"], es["1"]["category"]), ("reviewed", "low", "removal"))
        self.assertEqual(es["2"]["status"], "unreviewed")

    def test_timeline_filters_and_search(self):
        self.fixture("tl.xml", rss([("1", "Quota reduced", rfc(util.now()), "limit lowered"), ("2", "Other thing", rfc(util.now()), "zzz")]))
        vid = self.add_vendor("Timely", "payments")
        self.add_source(vid, "tl.xml", "rss")
        s, h, b = self.admin.get(f"/timeline?vendor={vid}&q=lowered")
        self.assertIn("Quota reduced", b)
        self.assertNotIn("Other thing", b)
        self.assertIn("No changes match", self.admin.get(f"/timeline?vendor={vid}&q=nothingatall")[2])
        s, h, b = self.admin.get("/timeline?from=2026-05-01&to=2026-01-01")
        self.assertIn("end date must not be before", b)
        self.assertIn("Quota reduced", self.admin.get(f"/timeline?vcat=payments&cat=scope+narrowing")[2])
        # raw snapshot shows the stored response with its hash
        sid = self.db.val("SELECT snapshot_id FROM entries WHERE vendor_id=? LIMIT 1", (vid,))
        s, h, b = self.admin.get(f"/snapshots/{sid}")
        sha = self.db.val("SELECT sha256 FROM snapshots WHERE id=?", (sid,))
        self.assertIn(sha, b)
        raw = self.admin.request("GET", f"/snapshots/{sid}/raw")[2]
        self.assertEqual(hashlib.sha256(raw).hexdigest(), sha)


class SourceForm(AppCase):
    def test_test_button_autodetect_and_validation(self):
        self.fixture("d.json", json.dumps({"version": "https://jsonfeed.org/version/1", "items": [{"id": "1", "title": "Hello"}]}))
        vid = self.add_vendor("Tester")
        s, h, b = self.admin.post(f"/vendors/{vid}/sources/test", url=self.fixture_url("d.json"), type="auto", interval_min="60", selector="")
        self.assertIn("Test fetch OK", b)
        self.assertIn("JSON Feed", b)
        self.assertEqual(self.db.val("SELECT COUNT(*) FROM sources WHERE vendor_id=?", (vid,)), 0)  # nothing saved
        self.fixture("disc.html", '<html><head><link rel="alternate" type="application/rss+xml" href="/_fixtures/disc.xml"></head><body>x</body></html>')
        self.fixture("disc.xml", rss([("1", "T", rfc(util.now()), "x")]))
        s, h, b = self.admin.post(f"/vendors/{vid}/sources/test", url=self.fixture_url("disc.html"), type="auto", interval_min="60", selector="")
        self.assertIn("autodiscovered", b)
        for bad, msg in (({"url": "ftp://x.example/feed"}, "Only http and https"), ({"url": "nope"}, "Only http and https"),
                         ({"interval_min": "5"}, "between 15 and 10080"), ({"selector": "div["}, "unsupported selector")):
            data = {"url": self.fixture_url("d.json"), "type": "auto", "interval_min": "60", "selector": "", **bad}
            s, h, b = self.admin.post(f"/vendors/{vid}/sources/new", **data)
            self.assertEqual(s, 400, bad)
            self.assertIn(msg, b)
        sid = self.add_source(vid, "d.json", "auto")
        s, h, b = self.admin.post(f"/vendors/{vid}/sources/new", url=self.fixture_url("d.json"), type="jsonfeed", interval_min="60")
        self.assertIn("already has a source with this URL", b)
        self.assertEqual(self.db.val("SELECT type FROM sources WHERE id=?", (sid,)), "jsonfeed")

    def test_selector_matches_nothing_warns(self):
        self.fixture("w.html", "<html><body><p>Some page text that is here</p></body></html>")
        vid = self.add_vendor("Warny")
        s, h, b = self.admin.post(f"/vendors/{vid}/sources/test", url=self.fixture_url("w.html"), type="html", interval_min="60", selector="#nope")
        self.assertIn("Selector matched nothing", b)

    def test_archive_restore_keeps_history_and_duplicates(self):
        self.fixture("ar.xml", rss([("1", "x", rfc(util.now()), "y")]))
        vid = self.add_vendor("Archy")
        self.add_source(vid, "ar.xml", "rss")
        s, h, b = self.admin.post("/vendors/new", name="archy", category="other")
        self.assertEqual(s, 400)
        self.assertIn("A vendor with this name exists", b)
        self.assertIn(f"/vendors/{vid}", b)
        ver = lambda: self.db.val("SELECT version FROM vendors WHERE id=?", (vid,))
        self.admin.post(f"/vendors/{vid}/archive", version=ver())
        self.assertNotIn("Archy", self.admin.get("/vendors")[2])
        self.assertIn("Archy", self.admin.get("/vendors?archived=1")[2])
        self.assertNotIn("Archy", self.admin.get("/churn")[2])
        self.assertEqual(self.db.val("SELECT COUNT(*) FROM entries WHERE vendor_id=?", (vid,)), 1)
        from driftwatch.scheduler import Scheduler
        self.assertNotIn(vid, [s["vendor_id"] for s in Scheduler(self.db, self.cfg).due_sources()])
        self.admin.post(f"/vendors/{vid}/restore", version=ver())
        self.assertIn("Archy", self.admin.get("/vendors")[2])
        # stale vendor edit is rejected
        old = ver() - 1
        s, h, b = self.admin.post(f"/vendors/{vid}/edit", name="Archy2", category="other", version=old)
        self.assertEqual(s, 409)
        self.assertIn("Changed by root at", b)
        self.assertEqual(self.db.val("SELECT name FROM vendors WHERE id=?", (vid,)), "Archy")

    def test_oversized_version_is_stale_not_500(self):
        vid = self.add_vendor("Bigver")
        big = "9" * 23
        for path, d in ((f"/vendors/{vid}/archive", {}), (f"/vendors/{vid}/restore", {}),
                        (f"/vendors/{vid}/edit", {"name": "B", "category": "other"})):
            self.assertLess(self.admin.post(path, version=big, **d)[0], 500, path)
        self.fixture("bv.xml", rss([("1", "x", rfc(util.now()), "y")]))
        eid = entries_of(self.db, self.add_source(self.add_vendor("Bigver2"), "bv.xml", "rss"))[0]["id"]
        for a in ("dismiss", "reopen", "triage"):
            self.assertLess(self.admin.post(f"/entries/{eid}/{a}", version=big, category="fix", impact="low")[0], 500, a)
        self.assertLess(self.admin.post("/triage/bulk", sel=[f"{eid}:{big}"], action="dismiss")[0], 500)

    def test_purge_requires_setting_and_name(self):
        vid = self.add_vendor("Purgeme")
        self.admin.post(f"/vendors/{vid}/archive", version=1)
        self.assertEqual(self.admin.post(f"/vendors/{vid}/purge", confirm="Purgeme")[0], 403)
        self.db.set_setting("vendors.allow_purge", "yes")
        self.addCleanup(self.db.set_setting, "vendors.allow_purge", "no")
        self.admin.post(f"/vendors/{vid}/purge", confirm="wrong")
        self.assertEqual(self.db.val("SELECT COUNT(*) FROM vendors WHERE id=?", (vid,)), 1)
        self.admin.post(f"/vendors/{vid}/purge", confirm="Purgeme")
        self.assertEqual(self.db.val("SELECT COUNT(*) FROM vendors WHERE id=?", (vid,)), 0)
        self.assertIn("vendor.purge", self.db.val("SELECT group_concat(action) FROM audit"))


class RolesAndUsers(AppCase):
    def test_roles_enforced_on_every_request(self):
        analyst = self.make_user("ann", "analyst")
        viewer = self.make_user("vic", "viewer")
        vid = self.add_vendor("Roley", client=analyst)
        self.assertEqual(viewer.post("/vendors/new", name="Nope", category="other")[0], 403)
        self.assertEqual(viewer.get("/vendors/new")[0], 403)
        self.assertEqual(viewer.post(f"/vendors/{vid}/archive", version=1)[0], 403)
        self.assertEqual(viewer.post(f"/sources/1/fetch")[0], 403)
        self.assertEqual(viewer.get("/triage")[0], 403)
        self.assertEqual(viewer.post("/triage/bulk", sel=["1:1"], action="dismiss")[0], 403)
        self.assertEqual(viewer.post("/entries/1/dismiss", version=1)[0], 403)
        for p in ("/users", "/audit", "/settings"):
            self.assertEqual(analyst.get(p)[0], 403, p)
            self.assertEqual(viewer.get(p)[0], 403, p)
        self.assertEqual(analyst.post("/users/new", username="zed", role="viewer")[0], 403)
        self.assertEqual(analyst.post("/settings")[0], 403)
        self.assertEqual(analyst.get("/keywords")[0], 200)  # keyword rules are analyst-editable
        self.assertEqual(viewer.get("/keywords")[0], 403)
        # viewers can read and export; edit buttons are hidden
        page = viewer.get(f"/vendors/{vid}")[2]
        self.assertNotIn("Add source", page)
        self.assertNotIn("/archive", page)
        self.assertEqual(viewer.get("/timeline")[0], 200)
        self.assertEqual(viewer.get("/churn.csv")[0], 200)
        self.assertEqual(viewer.get(f"/vendors/{vid}/evidence")[0], 200)
        self.assertNotIn("/triage", viewer.get("/timeline")[2])

    def test_anonymous_and_csrf(self):
        anon = Client(self.port)
        for p in ("/vendors", "/timeline", "/churn", "/churn.csv", "/snapshots/1/raw", "/exports/1/download", "/entries/1"):
            s, h, b = anon.get(p)
            self.assertEqual(s, 303, p)
            self.assertTrue(h["Location"].startswith("/login"), p)
        self.assertEqual(anon.request("GET", "/_fixtures/f1.xml")[0], 404)
        s, h, b = self.admin.request("POST", "/vendors/new", {"name": "NoToken", "category": "other"})
        self.assertEqual(s, 400)
        self.assertEqual(self.db.val("SELECT COUNT(*) FROM vendors WHERE name='NoToken'"), 0)

    def test_setup_only_once_and_validation(self):
        c = Client(self.port)
        s, h, b = c.get("/setup")
        self.assertEqual((s, h["Location"]), (303, "/login"))

    def test_one_time_password_flow_and_password_change(self):
        c = self.make_user("newbie", "analyst")  # make_user already walked through the forced change
        s, h, b = c.get("/vendors")
        self.assertEqual(s, 200)
        # wrong current password
        s, h, b = c.post("/profile/password", current="wrong", new="another-long-password", new2="another-long-password")
        self.assertIn("Current password is wrong", b)
        s, h, b = c.post("/profile/password", current=c.password, new="short", new2="short")
        self.assertIn("at least 12", b)
        # a fresh one-time password must be changed before anything else works
        s, h, b = self.admin.post("/users/new", username="forced", role="viewer")
        otp = re.search(r'<code id="otp">([^<]+)</code>', b).group(1)
        f = Client(self.port)
        f.login("forced", otp)
        s, h, b = f.get("/vendors")
        self.assertEqual((s, h["Location"]), (303, "/profile/password"))

    def test_duplicate_username_and_last_admin(self):
        s, h, b = self.admin.post("/users/new", username="ROOT", role="viewer")
        self.assertEqual(s, 400)
        self.assertIn("already taken", b)
        root_id = self.db.val("SELECT id FROM users WHERE username='root'")
        s, h, b = self.admin.post(f"/users/{root_id}/deactivate")
        self.assertIn("At least one admin is required", self.admin.get("/users")[2])
        self.assertEqual(self.db.val("SELECT active FROM users WHERE id=?", (root_id,)), 1)
        self.admin.post(f"/users/{root_id}/role", role="viewer")
        self.assertEqual(self.db.val("SELECT role FROM users WHERE id=?", (root_id,)), "admin")

    def test_deactivate_ends_sessions_and_lockout(self):
        c = self.make_user("temp1", "viewer")
        uid = self.db.val("SELECT id FROM users WHERE username='temp1'")
        self.assertEqual(c.get("/vendors")[0], 200)
        self.admin.post(f"/users/{uid}/deactivate")
        self.assertEqual(c.get("/vendors")[0], 303)
        self.assertEqual(Client(self.port).login("temp1", c.password)[0], 200)  # cannot sign in
        victim = self.make_user("victim", "viewer")
        bad = Client(self.port)
        for _ in range(5):
            bad.login("victim", "wrong-password-x")
        s, h, b = bad.login("victim", victim.password)
        self.assertEqual(s, 200)
        self.assertIn("locked", b)
        self.assertIn("login.locked", self.db.val("SELECT group_concat(action) FROM audit"))


class ReportsAndEvidence(AppCase):
    _n = 0

    def _seed(self):
        ReportsAndEvidence._n += 1
        now = util.now()
        self.fixture("ch.xml", rss([("1", "API removed", rfc(now), "The endpoint was removed."),
                                    ("2", "Old API deprecated", rfc(now), "deprecated"),
                                    ("3", "Noise post", rfc(now), "marketing"),
                                    ("4", "Fixed typo", rfc(now), "nothing")]))
        vid = self.add_vendor(f"Churny{self._n}", "identity")
        sid = self.add_source(vid, "ch.xml", "rss")
        ids = {e["dedup_key"]: e for e in entries_of(self.db, sid)}
        self.admin.post(f"/entries/{ids['1']['id']}/triage", category="removal", impact="high", note="critical", version=1)
        self.admin.post(f"/entries/{ids['3']['id']}/dismiss", version=1)
        return vid, sid

    def test_churn_scores_match_rules_and_csv(self):
        vid, sid = self._seed()
        # removal(5) x high(3) = 15; unreviewed deprecation counts 3 x1; dismissed 0; unreviewed 'other' 0
        s, h, b = self.admin.get("/churn.csv?months=12")
        rows = list(csv.reader(io.StringIO(b.lstrip("﻿"))))
        row = [r for r in rows if r[0] == f"Churny{self._n}"][0]
        header = rows[0]
        self.assertEqual(int(row[header.index("Total")]), 18)
        self.assertEqual(int(row[header.index("removal")]), 1)
        self.assertEqual(int(row[header.index("deprecation")]), 1)
        month = util.now().strftime("%Y-%m")
        self.assertEqual(int(row[header.index(month)]), 18)
        page = self.admin.get("/churn")[2]
        self.assertIn(f"Churny{self._n}", page)
        self.assertIn(f"/timeline?vendor={vid}", page)
        self.db.set_setting("churn.count_basis", "confirmed_only")
        self.addCleanup(self.db.set_setting, "churn.count_basis", "include_unreviewed")
        page = self.admin.get("/churn")[2]
        self.assertIn("unreviewed entries in this period are excluded", page)
        rows = list(csv.reader(io.StringIO(self.admin.get("/churn.csv")[2].lstrip("﻿"))))
        self.assertEqual(int([r for r in rows if r[0] == f"Churny{self._n}"][0][rows[0].index("Total")]), 15)
        # sorting by a category column works
        self.assertEqual(self.admin.get("/churn?sort=removal&dir=desc")[0], 200)

    def test_evidence_pack_verifies_and_is_audited(self):
        vid, sid = self._seed()
        today = util.now().date()
        data = dict(**{"from": str(today - timedelta(days=30)), "to": str(today)}, min_impact="low")
        s, h, raw = self.admin.request("POST", f"/vendors/{vid}/evidence", {**data, "_csrf": self.admin.csrf})
        self.assertEqual(s, 200)
        self.assertEqual(h["Content-Type"], "application/zip")
        z = zipfile.ZipFile(io.BytesIO(raw))
        names = z.namelist()
        for n in ("report.html", "entries.csv", "manifest.json"):
            self.assertIn(n, names)
        manifest = json.loads(z.read("manifest.json"))
        listed = {f["path"] for f in manifest["files"]}
        self.assertEqual(listed, set(names) - {"manifest.json"})
        for f in manifest["files"]:
            self.assertEqual(hashlib.sha256(z.read(f["path"])).hexdigest(), f["sha256"], f["path"])
        self.assertTrue(any(n.startswith("snapshots/") for n in names))
        # dismissed entries are excluded by default
        rows = list(csv.DictReader(io.StringIO(z.read("entries.csv").decode())))
        self.assertEqual(len(rows), 3)
        self.assertNotIn("Noise post", [r["title"] for r in rows])
        self.assertIn("API removed", z.read("report.html").decode())
        mhash = hashlib.sha256(z.read("manifest.json")).hexdigest()
        audit = self.db.val("SELECT detail FROM audit WHERE action='export.evidence' ORDER BY id DESC")
        self.assertIn(mhash, audit)
        self.assertIn("Past evidence packs", self.admin.get(f"/vendors/{vid}")[2])
        xid = self.db.val("SELECT id FROM exports ORDER BY id DESC")
        self.assertEqual(hashlib.sha256(zipfile.ZipFile(io.BytesIO(self.admin.request("GET", f"/exports/{xid}/download")[2])).read("manifest.json")).hexdigest(), mhash)
        # setting: dismissed included and marked
        self.db.set_setting("export.include_dismissed", "yes")
        self.addCleanup(self.db.set_setting, "export.include_dismissed", "no")
        s, h, raw = self.admin.request("POST", f"/vendors/{vid}/evidence", {**data, "_csrf": self.admin.csrf})
        self.assertIn("DISMISSED", zipfile.ZipFile(io.BytesIO(raw)).read("report.html").decode())

    def test_evidence_filters_empty_and_invalid(self):
        vid, sid = self._seed()
        today = util.now().date()
        post = lambda **kw: self.admin.post(f"/vendors/{vid}/evidence", **kw)
        s, h, b = post(**{"from": str(today), "to": str(today - timedelta(days=1)), "min_impact": "low"})
        self.assertEqual(s, 400)
        self.assertIn("must not be before", b)
        far = str(today - timedelta(days=900))
        s, h, b = post(**{"from": far, "to": far, "min_impact": "low"})
        self.assertEqual(s, 200)
        self.assertIn("No entries match", b)  # warns first
        s, h, raw = self.admin.request("POST", f"/vendors/{vid}/evidence", {"from": far, "to": far, "min_impact": "low", "confirm_empty": "1", "_csrf": self.admin.csrf})
        z = zipfile.ZipFile(io.BytesIO(raw))
        self.assertIn(far, z.read("report.html").decode())
        # min impact + category filters
        s, h, raw = self.admin.request("POST", f"/vendors/{vid}/evidence", {"from": str(today - timedelta(days=5)), "to": str(today), "min_impact": "high", "_csrf": self.admin.csrf})
        rows = list(csv.DictReader(io.StringIO(zipfile.ZipFile(io.BytesIO(raw)).read("entries.csv").decode())))
        self.assertEqual([r["title"] for r in rows], ["API removed"])
        # size limit
        self.db.set_setting("export.max_mb", "1")
        self.addCleanup(self.db.set_setting, "export.max_mb", "200")
        big = self.db.one("SELECT id FROM snapshots ORDER BY id DESC")[0]
        self.db.x("UPDATE snapshots SET size=? WHERE id IN (SELECT snapshot_id FROM entries WHERE vendor_id=?)", (2 * 1024 * 1024, vid))
        s, h, b = post(**{"from": str(today - timedelta(days=5)), "to": str(today), "min_impact": "low"})
        self.assertEqual(s, 400)
        self.assertIn("Narrow the date range", b)

    def test_settings_and_keywords_roundtrip(self):
        bad = {f"s:{k}": v for k, v in self.db.all_settings().items()}
        bad["s:fetch.default_interval_minutes"] = "5"
        s, h, b = self.admin.post("/settings", **bad)
        self.assertEqual(s, 400)
        self.assertIn("between 15 and 10080", b)
        vals = {f"s:{k}": v for k, v in self.db.all_settings().items()}
        vals["s:diff.noise_chars"] = "30"
        self.assertEqual(self.admin.post("/settings", **vals)[0], 303)
        self.assertEqual(self.db.int_setting("diff.noise_chars"), 30)
        self.addCleanup(self.db.set_setting, "diff.noise_chars", "20")
        self.assertIn("settings.update", self.db.val("SELECT group_concat(action) FROM audit"))
        kw = {f"kw:{c}": "" for c in ("deprecation", "removal", "breaking change", "default change", "scope narrowing", "security", "new capability", "fix")}
        kw["kw:fix"] = "bugfix\nrepaired"
        kw["kw:deprecation"] = "deprecat"
        self.assertEqual(self.admin.post("/keywords", **kw)[0], 303)
        self.fixture("kw.xml", rss([("1", "We repaired it", rfc(util.now()), "x")]))
        sid = self.add_source(self.add_vendor("Kwco"), "kw.xml", "rss")
        self.assertEqual(entries_of(self.db, sid)[0]["suggested_category"], "fix")


class Ops(unittest.TestCase):
    def test_demo_data_and_backup_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config.load(env={})
            cfg.data_dir = Path(tmp) / "d1"
            config.prepare_data_dir(cfg)
            db = Database(cfg.db_path)
            db.migrate()
            created, otps = demo.load(db, cfg)
            self.assertEqual((created["vendors"], created["sources"]), (8, 16))
            self.assertTrue(130 <= created["entries"] <= 190, created)
            self.assertEqual(set(otps), {"demo-analyst", "demo-viewer"})
            self.assertEqual({r[0] for r in db.q("SELECT DISTINCT type FROM sources")}, {"rss", "atom", "jsonfeed", "github", "html"})
            self.assertEqual({r[0] for r in db.q("SELECT DISTINCT status FROM entries")}, {"unreviewed", "reviewed", "dismissed"})
            with self.assertRaises(demo.DemoError):
                demo.load(db, cfg)
            # backup while open, restore into a fresh directory
            class A: file = str(Path(tmp) / "b.tgz")
            self.assertEqual(cli.cmd_backup(A, cfg), 0)
            cfg2 = config.load(env={})
            cfg2.data_dir = Path(tmp) / "d2"
            class R: file = A.file; force = False
            self.assertEqual(cli.cmd_restore(R, cfg2), 0)
            db2 = Database(cfg2.db_path)
            self.assertEqual(db2.val("SELECT COUNT(*) FROM entries"), db.val("SELECT COUNT(*) FROM entries"))
            self.assertEqual(db2.val("SELECT COUNT(*) FROM audit WHERE action='restore'"), 1)
            self.assertEqual(cli.cmd_restore(R, cfg2), 1)  # refuses to overwrite without --force
            db.close(); db2.close()

    def test_config_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "file"
            f.write_text("x")
            cfg = config.load(env={"DRIFTWATCH_DATA_DIR": str(f / "sub")})
            with self.assertRaises(config.ConfigError) as cm:
                config.prepare_data_dir(cfg)
            self.assertIn(str(f / "sub"), str(cm.exception))
        self.assertEqual(config.load(env={"DRIFTWATCH_LISTEN": "0.0.0.0:9000"}).port, 9000)
        self.assertEqual(config.load(env={}).listen, "127.0.0.1:8080")


if __name__ == "__main__":
    unittest.main()


class Findings(AppCase):
    def test_interval_bounds_and_nonnumeric(self):
        vid = self.add_vendor("Intervalco")
        self.fixture("iv.xml", rss([("1", "x", rfc(util.now()), "y")]))
        for n, (m, exp) in enumerate({"15": 303, "10080": 303, "14": 400, "10081": 400, "0": 400, "-5": 400, "abc": 400}.items()):
            self.fixture(f"iv{n}.xml", rss([("1", "x", rfc(util.now()), "y")]))
            s, h, b = self.admin.post(f"/vendors/{vid}/sources/new", url=self.fixture_url(f"iv{n}.xml"), type="rss", interval_min=m)
            self.assertEqual(s, exp, m)
