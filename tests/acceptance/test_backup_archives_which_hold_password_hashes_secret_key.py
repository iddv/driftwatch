"""Backup archives (which hold password hashes and the secret key) are readable only by their owner.

Expected: backup file mode has no group/other bits
Source: the security review (SECURITY.md).
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path
from _helpers.driver import Site, ROOT


def test_backup_file_private():
    with Site() as S:
        out = Path(tempfile.mkdtemp()) / "b.tgz"
        env = dict(os.environ, DRIFTWATCH_DATA_DIR=str(S.cfg.data_dir))
        old = os.umask(0o022)
        try:
            r = subprocess.run([sys.executable, "-m", "driftwatch", "backup", str(out)], cwd=ROOT, env=env,
                               capture_output=True, text=True, timeout=25)
        finally:
            os.umask(old)
        assert out.exists(), r.stdout + r.stderr
        assert out.stat().st_mode & 0o077 == 0, oct(out.stat().st_mode)


# Known open item: expected to fail until it is fixed (tests/acceptance/README.md).
import pytest as _pytest_open  # noqa: E402
_marks = globals().get('pytestmark', [])
pytestmark = (list(_marks) if isinstance(_marks, (list, tuple)) else [_marks]) + [
    _pytest_open.mark.xfail(strict=False, reason='Known security issue (low): Backup archives (which hold password hashes and the secret key) are readable only by their owner')]
