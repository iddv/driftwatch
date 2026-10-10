"""Admin manages users.

Expected: works
Source: "SCOPE F8"
Flow: F8 in SCOPE.md.
"""

from _helpers.driver import *

def test_f8():
    with Site() as s:
        st, h, b = s.admin.get("/users"); assert "Add user" in b
        st, h, b = s.admin.post("/users/new", username="anna", role="analyst"); assert "one-time" in b.lower()
        otp = re.search(r'<code id="otp">([^<]+)</code>', b).group(1)
        assert s.admin.post("/users/new", username="anna", role="viewer")[0] == 400
        a = Client(s.port); assert a.login("anna", otp)[0] == 303
        st, h, b = a.request("GET", "/vendors"); assert st == 303 and "password" in h["Location"]
        st, h, b = a.post("/profile/password", current="wrong-current-pw", new="brand-new-password", new2="brand-new-password"); assert st == 400 and "wrong" in b.lower()
        assert a.post("/profile/password", current=otp, new="brand-new-password", new2="brand-new-password")[0] == 303
        assert a.get("/vendors")[0] == 200
        st, h, b = s.admin.post("/users/new", username="vi", role="viewer"); vo = re.search(r'<code id="otp">([^<]+)</code>', b).group(1)
        vw = Client(s.port); vw.login("vi", vo); vw.post("/profile/password", current=vo, new="viewer-password-1", new2="viewer-password-1")
        v = s.add_vendor("A"); b = vw.get(f"/vendors/{v}")[2]
        assert "Add source" not in b and "Archive" not in b and vw.post(f"/vendors/{v}/archive", version="1")[0] == 403 and vw.get("/vendors/new")[0] == 403
        uid = s.db.val("select id from users where username='vi'")
        s.admin.post(f"/users/{uid}/deactivate"); assert vw.get("/vendors")[0] in (302, 303)
        st, h, b = s.admin.post(f"/users/{uid}/reactivate"); assert Client(s.port).login("vi", "viewer-password-1")[0] == 303
        st, h, b = s.admin.post(f"/users/{uid}/reset"); assert "one-time" in b.lower()
        rid = s.db.val("select id from users where username='root'")
        st, h, b = s.admin.post(f"/users/{rid}/deactivate"); assert "At least one admin is required" in s.admin.get(h["Location"])[2]
        assert "login.success" in s.admin.get("/audit")[2] and "user.create" in s.admin.get("/audit?action=user.create")[2]
        assert s.admin.get("/audit?user=anna")[0] == 200
