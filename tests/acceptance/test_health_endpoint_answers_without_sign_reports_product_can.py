"""A health endpoint answers without sign-in and reports the product can work (database opens).

Expected: GET /health returns 200 with no cookie
Source: the readiness checks (READINESS.md).
"""

import http.client
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from _helpers.driver import ROOT  # noqa: F401

REPO = Path(__file__).resolve().parent.parent.parent


def test_health_without_login():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]; s.close()
    with tempfile.TemporaryDirectory() as d:
        env = dict(os.environ, DRIFTWATCH_LISTEN=f"127.0.0.1:{port}", DRIFTWATCH_DATA_DIR=d, PYTHONPATH=str(REPO))
        p = subprocess.Popen([sys.executable, "-m", "driftwatch", "serve"], cwd=d, env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            status = None
            for _ in range(60):
                try:
                    c = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                    c.request("GET", "/health")
                    status = c.getresponse().status
                    break
                except OSError:
                    time.sleep(0.25)
            assert status == 200, f"/health returned {status}"
        finally:
            p.terminate(); p.wait(10)
