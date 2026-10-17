# Security

## Reporting a security issue

Please report security problems privately, not in a public issue: use the repository host's private vulnerability reporting (on GitHub: Security, then Report a vulnerability), or write to the maintainers directly. Include the version, the steps to reproduce and what an attacker could do. You will get an answer within a few working days.

## Known issues

Open at the last release:

### S5 (low): Database and backup archives are world-readable

- Where: driftwatch/cli.py backup; data/driftwatch.db
- What happens: -rw-rw-r-- backup (contains secret.key and password hashes); -rw-r--r-- driftwatch.db
- What should happen: 0600 files and a 0700 data directory
- Reproduce: `driftwatch backup /tmp/b.tgz; ls -l /tmp/b.tgz data/driftwatch.db`
- Test: `tests/acceptance/test_backup_archives_which_hold_password_hashes_secret_key.py` (marked as a known open item)

### S6 (low): Setup page is open to whoever connects first

- Where: /setup
- What happens: /setup is unauthenticated until an admin exists. The session cookie now carries Secure when the request has `X-Forwarded-Proto: https`
- What should happen: set up a network-exposed fresh install at once (documented in the README and on the setup page)
- Reproduce: `open /setup on a network-exposed fresh install`
- Test: `tests/acceptance/test_session_cookie_secure_over_https.py`
