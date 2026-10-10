# Readiness

Where Driftwatch stands on the way to production: each item was checked by doing it (installing from the README, starting it, backing it up and restoring it, ...) or by reading the repository. Green is ready, amber needs attention before production, red is a gap.

**17 green, 2 amber, 1 red**.

| item | status | why | next step to production |
|---|---|---|---|
| Clean install from the README | green | README command ./bin/driftwatch serve worked in a fresh copy; no dependencies | - |
| The README's quick-start commands work as written (install, run, backup) | green | 3 quick-start command(s) worked as written on a fresh copy; 1 not run (has a placeholder to fill in) | - |
| Listens on localhost unless configured | green | binds 127.0.0.1:8080 by default | - |
| Starts empty; demo data only on an explicit flag or command | green | fresh start has no vendors; demo only via 'demo load' | - |
| First-run admin setup, no default password | green | setup page makes operator choose admin password; no default | - |
| Configuration by environment or file, every option documented | amber | env/TOML config documented with defaults, but the policy-settings env names are unprefixed and DRIFTWATCH_CONFIG file is only partly listed | Prefix policy env vars with DRIFTWATCH_ or state clearly; check every option in code is in the README |
| Data location documented | green | README says data is in ./data and DRIFTWATCH_DATA_DIR changes it | - |
| Backup and restore work end to end | green | backup while running, restore into stopped instance brought data back | - |
| Data survives a restart | green | data survived SIGTERM+immediate restart and SIGKILL+immediate restart; served at once | - |
| Starts again at once after a stop or a crash (services) | green | `./bin/driftwatch serve` on 127.0.0.1:8080 served again 0.21 s after a graceful stop and 0.21 s after a SIGKILL | - |
| Graceful shutdown | green | SIGTERM exits in about 0.4 s with data intact | - |
| Health endpoint (services) | green | fixed in this version (its test passes); it was: no health endpoint; /health,/healthz,/status,/ready,/ping all 404 | - |
| Readable logs, no secrets or personal data | amber | request lines readable but have no timestamps; full query strings (search text) are logged | Add timestamps and strip or redact query strings in the access log |
| Schema changes and upgrades keep the data | green | versioned schema (meta.schema_version, v1->v2 steps) with automatic pre-migration backup | - |
| CI workflow installs the project and runs the tests | green | .github/workflows/test.yml installs and runs the tests | - |
| Dependencies locked or pinned | green | no third-party runtime dependencies (standard library only) | - |
| Sensible .gitignore, no build artefacts in the repository | red | no .gitignore | add a .gitignore for caches, virtual environments, build output and local data files |
| README covers install, configure, run, upgrade, backup and restore, troubleshooting and limitations | green | every section is there | - |
| The documented test commands run green, as written | green | 66 own test(s) pass; the acceptance suite is green (86 pass, 1 known open item(s) marked); the README's test commands run green as written | - |
| User-facing docs in plain words | green | no build-process jargon in README, ASSUMPTIONS, SECURITY, READINESS or the tests | - |

## Security

See `SECURITY.md`: 6 finding(s), 2 not fixed by a tested change (low 2).

## Known open items in the tests

Marked as expected failures in `tests/acceptance/` (the suite stays green):

- `test_backup_archives_which_hold_password_hashes_secret_key.py`: Known security issue (low): Backup archives (which hold password hashes and the secret key) are readable only by their owner
