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

### S6 (low): Session cookie has no Secure flag, and the setup page is open to whoever connects first

- Where: driftwatch/v_auth.py:8; /setup
- What happens: dw_sess=...; Path=/; HttpOnly; SameSite=Lax. /setup is unauthenticated until an admin exists
- What should happen: Secure when served over HTTPS; document that exposed fresh installs must be set up at once
- Reproduce: `read Set-Cookie after POST /login; open /setup on a network-exposed fresh install`

## What was checked

The security review that ran before each release (threat model, probes, findings) is published with that release in its checks asset.
