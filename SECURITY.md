# Security

How Driftwatch was reviewed for security before its first release, what was found, and what is still open.

## Threat model

Self-hosted Python stdlib web app (127.0.0.1:8080) with SQLite. No anonymous access except setup (until an admin exists), login, logout, static files and a fixture route guarded by an HMAC header. Staff routes are gated by viewer/analyst/admin roles. The server also fetches operator-supplied URLs (analyst/admin) and runs a scheduler.

### Entry points

| entry point | who can reach it | authentication | notes |
|---|---|---|---|
| GET/POST /setup | public | none; only works until the first admin exists | first-run race: whoever reaches the port first creates the admin |
| GET/POST /login, POST /logout | public | username+password, per-account lockout (5 failures/15 min) |  |
| GET /static/*, GET /_fixtures/<name> | public | fixtures need an HMAC header derived from the session secret | names restricted to [\w.-]+ |
| Read pages: /vendors /timeline /churn /churn.csv /entries /snapshots /vendors/N/evidence /exports/N/download | staff | session cookie (viewer or above) |  |
| Vendors, sources, fetch, test fetch, triage, keywords | staff | session cookie + CSRF token (analyst or above) | source test/save makes server-side HTTP requests to any http(s) URL |
| /users*, /audit, /settings, vendor purge | admin | session cookie + CSRF token |  |
| CLI: serve, demo load, backup, restore, test | local | OS user | data dir, DB and backup files |
| Scheduler (background) | local | n/a | fetches sources on an interval |

### Assets

| asset | kind | where |
|---|---|---|
| user password hashes (scrypt) | secrets | data/driftwatch.db and backups |
| session secret (CSRF and fixture token) | secrets | data/secret.key, backups |
| change history, snapshots, evidence packs | integrity | data/ |
| service availability | availability | HTTP listener |
| internal network reachable from the host | network | source fetcher |

## What was checked, and how

The product was started as its README says and probed while running.

| area | check | result | evidence |
|---|---|---|---|
| authN/authZ | every route anonymously (20 GETs, 7 POSTs) | pass | all redirect to /login or setup, except static and fixtures (404 without header) |
| authN/authZ | viewer on edit, user, settings, purge, triage routes | pass | 403 on all |
| authN/authZ | analyst on /users /audit /settings and role change | pass | 403 |
| hostile HTTP | negative Content-Length | fail | server blocks reading the body; 300 MiB streamed raised RSS 48 -> 357 MiB, no response |
| hostile HTTP | non-numeric Content-Length | fail | HTTP 500, traceback in the server log |
| hostile HTTP | Content-Length 99999999999 and 3 MB | pass | 413 at once |
| hostile HTTP | idle half-open connections (300 of them) | fail | each holds a thread; 303 threads, RSS 48 -> 555 MiB, nothing times out |
| hostile HTTP | page=-1, page=huge, months=-5, huge/non-numeric ids | pass | 200/404, no 500 |
| hostile HTTP | 10,000-level JSON, NaN/Infinity | n/a | the app accepts only form-encoded bodies, no JSON endpoints |
| injection | SQL injection in q, vendor, ids, fields | pass | 200/404, parametrised queries |
| injection | stored XSS in vendor name and notes; reflected XSS in query strings | pass | HTML escaped everywhere tried; CSP default-src 'self' |
| injection | CSRF: POST with no token, another user's token | pass | 400 |
| injection | CSRF: foreign Origin with valid token | pass | the token is bound to the session and not forgeable cross-site |
| injection | open redirect via next= | pass | //evil, http://evil, backslash all rejected |
| injection | path traversal in /_fixtures and /static | pass | 404 |
| injection | SSRF through source Test/Save | fail | an analyst fetched http://127.0.0.1:9911/ and the body was shown; closed ports give distinct errors |
| authentication | lockout | pass | locked after 5 wrong passwords for 15 minutes |
| authentication | cookie flags | pass | HttpOnly and SameSite=Lax set; no Secure flag (plain HTTP service; low, see s6) |
| authentication | logout kills session | pass | old cookie gets a redirect to /login |
| authentication | password change ends other sessions; scrypt n=2^14 with salt | pass | code review |
| secrets and defaults | default credentials, hard-coded secrets | pass | none; session secret random, saved 0600 in secret.key; no passwords or tokens in log |
| secrets and defaults | file permissions of DB and backup | fail | driftwatch.db 0644 and backup .tgz 0664 (both hold hashes; the backup holds secret.key) |
| error pages | bad ids, bad dates, missing snapshot/export | pass | clean 404/400 pages, no traceback, paths or SQL |
| dependencies | no third-party dependencies | n/a | pyproject lists dependencies = [] |

## Findings

| | severity | finding | status |
|---|---|---|---|
| S1 | high | A negative Content-Length makes the server read the body without a limit | fixed (a test checks it) |
| S2 | high | Slow or idle connections are never timed out (thread and memory exhaustion by anyone) | fixed (a test checks it) |
| S3 | medium | Non-numeric Content-Length gives HTTP 500 | fixed (a test checks it) |
| S4 | medium | Server-side request forgery: analysts can make the server fetch loopback and private-network URLs and read the result | fixed (a test checks it) |
| S5 | low | Database and backup archives are world-readable | open |
| S6 | low | Session cookie has no Secure flag, and the setup page is open to whoever connects first | open |

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

## Dependency audit

- Tool: pip-audit; result: no_dependencies.
- pyproject.toml declares dependencies = []; the app uses only the Python standard library

## Known limits

- This was a time-boxed review of v1 by one reviewer with the code and a running copy: scripted probes and manual checks, not a penetration test or an external audit.
- TLS and reverse-proxy deployments were not tested
- Stored XSS through fetched feed and HTML content was not proven end to end: my fixture produced no entry, so I only reviewed the escaping in code
- Only vendor name/notes were XSS-tested live
- restore and demo commands, the settings page and user-admin flows were not attacked in depth
- CSRF relies on the token only; there is no Origin header check
- the 413 path does not drain the body on a kept-alive connection (desync not tested)

## Reporting a security issue

Please report security problems privately, not in a public issue: use the repository host's private vulnerability reporting (on GitHub: Security, then Report a vulnerability), or write to the maintainers directly. Include the version, the steps to reproduce and what an attacker could do. You will get an answer within a few working days.
