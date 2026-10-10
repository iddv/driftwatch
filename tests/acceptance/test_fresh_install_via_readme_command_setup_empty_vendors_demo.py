"""Fresh install via README command, setup, empty vendors, demo load.

Expected: service starts, setup creates admin, empty Vendors page w/ Add vendor + demo note, 8 vendors after demo
Source: "SCOPE F1"
Flow: F1 in SCOPE.md.
"""

import os, re, socket, subprocess, sys, tempfile, time
from pathlib import Path
from _helpers.driver import Client, ROOT, PW


def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def test_f1():
    port = free_port()
    data = tempfile.mkdtemp()
    env = dict(os.environ, DRIFTWATCH_LISTEN=f"127.0.0.1:{port}", DRIFTWATCH_DATA_DIR=data)
    proc = subprocess.Popen([str(ROOT / "bin" / "driftwatch"), "serve"], env=env, cwd=data, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", port), 0.2).close(); break
            except OSError:
                time.sleep(0.2)
        c = Client(port)
        s, h, b = c.request("GET", "/vendors")
        assert s == 303 and h["Location"].endswith("/setup")
        tok = c.token("/setup")
        s, h, b = c.request("POST", "/setup", {"_csrf": tok, "username": "root", "password": "short", "password2": "short"})
        assert s == 400 and b"at least" in b
        s, h, b = c.request("POST", "/setup", {"_csrf": tok, "username": "root", "password": PW, "password2": PW})
        assert s == 303
        s, h, b = c.get("/vendors")
        assert s == 200 and "Add vendor" in b and "demo load" in b
        assert not re.search(r'href="/vendors/\d+"', b)
        r = subprocess.run([str(ROOT / "bin" / "driftwatch"), "demo", "load"], env=env, cwd=data, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        assert "8 vendors" in r.stdout and "one-time password" in r.stdout
        s, h, b = c.get("/vendors")
        assert len(set(re.findall(r'href="/vendors/(\d+)"', b))) == 8
    finally:
        proc.terminate(); proc.wait(5)
