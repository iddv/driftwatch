"""Demo refuses with existing vendors.

Expected: Without the option it refuses and nothing is added; with the option the demo data is added
Source: "The demo command is run on a system that already has vendors: it refuses, unless run with `--force-into-existing`."
"""

from _helpers.driver import *

import subprocess, os
def test_demo_refuses_existing_vendors():
    with Site() as s:
        s.add_vendor("Mine")
        env = dict(os.environ, DRIFTWATCH_DATA_DIR=str(s.cfg.data_dir), DRIFTWATCH_LISTEN=f"127.0.0.1:{s.port}")
        run = lambda *a: subprocess.run([str(ROOT / "bin" / "driftwatch"), *a], env=env, capture_output=True, text=True, cwd=str(s.cfg.data_dir))
        r = run("demo", "load")
        assert r.returncode != 0
        assert s.db.val("select count(*) from vendors") == 1
        r = run("demo", "load", "--force-into-existing")
        assert r.returncode == 0, r.stderr
        assert s.db.val("select count(*) from vendors") == 9
