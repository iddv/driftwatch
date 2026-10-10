# AGENTS.md — Driftwatch

A self-hosted tracker that follows the public changelogs and release notes of the vendors you depend on, flags changes to documented behavior, defaults and deprecations, and keeps a per-vendor history of how often things shifted under you.

Built by an autonomous build (see NOTICE); maintained through GitHub issues by the owner, by
bears, and by any coding agent that reads this file. CLAUDE.md imports this file.

## What this is

- **For:** Small engineering, ops or platform teams, and serious self-hosters, who rely on a handful of hosted services (databases, identity providers, secrets managers, agent runtimes) and keep getting surprised by silent default changes and deprecations at renewal or upgrade time.
- **Does:** Driftwatch is a self-hosted web service that a platform, security or vendor-management team runs for itself. In v1 the team registers the vendors it depends on, such as databases, identity providers and secrets managers. For each vendor it adds the public changelogs, release feeds and docs pages to watch.
- **Stack:** Python 3.11+, standard library only, SQLite, one process on 127.0.0.1.
- **Scope:** `SCOPE.md` (users, numbered flows F1–F8, domain rules, definition of done).
  `ASSUMPTIONS.md` lists the questions the idea left open and what this version does.

## Setup, run, test

These commands are run by CI exactly as written (`.github/workflows/ci.yml`, job `agents-md`).
If you change a command, change it here in the same commit. A line marked `# serve` starts the
service; the check waits for it to answer on 127.0.0.1, then stops it.

```sh
./bin/driftwatch serve   # serve: http://127.0.0.1:8080/
./bin/driftwatch test   # the product's own tests
python -m pip install pytest==8.3.3 && python -m pytest tests/acceptance   # the acceptance suite
```

- pytest is only needed for the acceptance suite; install it inside a virtual environment if
  your system Python refuses.
- Demo data: `see README` (empty install only).
- Backup and restore: `see README`, `see README`.
- Configuration: environment variables or `a config file` (see README › Configuration).

## Architecture in brief

| Path | Holds |
|---|---|
| `driftwatch/__main__.py` | Runs the package as a command: `python -m driftwatch`. |
| `driftwatch/auth.py` | Users, passwords, lockout and sessions. |
| `driftwatch/cli.py` | Command line entry point: serve, demo load, backup, restore, test. |
| `driftwatch/config.py` | Configuration from environment variables and an optional TOML file. |
| `driftwatch/db.py` | SQLite storage: schema, migrations, settings, audit log. |
| `driftwatch/demo.py` | Demo data: 8 vendors, 16 sources, ~150 entries over 18 months, served from local fixture files. |
| `driftwatch/evidence.py` | Evidence pack: HTML report, CSV, raw snapshots and a hashed manifest in one zip. |
| `driftwatch/fetcher.py` | Outbound HTTP: limits, redirects, proxy, robots.txt, type detection. |
| `driftwatch/ingest.py` | Fetch a source, store the snapshot and record changes. |
| `driftwatch/parsing.py` | Parsers for RSS 2.0, Atom, JSON Feed, GitHub releases and HTML pages (DOM, CSS selectors, block diff). |
| `driftwatch/router.py` | Request/response objects and the route table shared by all views. |
| `driftwatch/scheduler.py` | Background scheduler: picks due sources and fetches them with bounded concurrency. |
| `driftwatch/scoring.py` | Churn scoring, computed from entries at query time. |
| `driftwatch/ui.py` | HTML building blocks: layout, forms, formatting. |
| `driftwatch/util.py` | Small shared helpers: time, escaping, hashing. |
| `driftwatch/v_admin.py` | Users, audit log and settings (F8, M11, M12). |
| `driftwatch/v_auth.py` | Setup, sign-in, sign-out and own-password views. |
| `driftwatch/v_reports.py` | Timeline, snapshots, churn report and evidence packs (F5, F6, F7). |
| `driftwatch/v_triage.py` | Triage queue and entry detail/actions (F4), plus the shared entry filter used by the timeline. |
| `driftwatch/v_vendors.py` | Vendor and source management views (F2, F3). |
| `driftwatch/web.py` | HTTP server, dispatch, security headers, static and fixture routes. |
| `tests/test_flows.py` | Unit tests (the product's own test command). |
| `tests/test_parsing.py` | Unit tests (the product's own test command). |
| `tests/test_range_default.py` | Unit tests (the product's own test command). |
| `tests/test_security.py` | Unit tests (the product's own test command). |
| `tests/test_settings_s1.py` | Unit tests (the product's own test command). |
| `tests/test_settings_s2.py` | Unit tests (the product's own test command). |
| `tests/test_settings_s3.py` | Unit tests (the product's own test command). |
| `tests/test_settings_s4.py` | Unit tests (the product's own test command). |
| `tests/test_settings_s5.py` | Unit tests (the product's own test command). |
| `tests/test_settings_s6.py` | Unit tests (the product's own test command). |
| `tests/acceptance/` | The acceptance suite: one file per behaviour, through the real interface (pytest). |
| `tests/acceptance/_helpers/` | Drivers the acceptance tests share (start the service, sign in, submit forms). |

Data lives in `./data`; the schema is versioned (the schema version is stored with the data; pending migrations run at start), and a
pre-migration backup is written before any upgrade.

Snapshots and entries are not deleted automatically; they are removed only when an admin purges a vendor (requires `vendors.allow_purge` to be on).

## Conventions

- Standard library only. Do not add a dependency to fix a bug.
- Operator settings (binary business rules) are settings with an environment override; a new one
  goes in the Settings page, the README table, `ASSUMPTIONS.md`, and gets an acceptance test per
  value. Never hard-code one side of a business rule.
- Every behaviour has one acceptance test file, `tests/acceptance/test_<what_it_checks>.py`,
  with a plain docstring (what it checks, what is expected, where the rule comes from). Helpers
  live in `tests/acceptance/_helpers/` and drive the product's real interface.
- The server checks roles and CSRF on every state-changing request; templates escape everything.
- Plain words in user-facing files: no build-process jargon, no internal ids.

## The acceptance suite, readiness and security

- `tests/acceptance/README.md` lists the **known open items**: tests marked
  `xfail(strict=False)` because the behaviour is not there yet. **To fix one:** make the test
  pass, then delete the mark block at the end of its file and the line in that README. CI fails
  if an xfail test now passes and still carries the mark.
- `READINESS.md` is the operational scorecard (install, localhost default, empty start, first
  admin, backup, restart, logs, CI, docs). Keep it true: a change that moves an item from amber
  to green edits the row.
- `SECURITY.md` is the threat model, what was probed, and the findings with their status. A fix
  for a finding changes its status there and names its test. Report new weaknesses privately
  (see its last section), never in a public issue.

## Operator settings

Set by an Admin on the in-app Settings page; each has an environment variable that wins when set (README › Configuration). `ASSUMPTIONS.md` says why each exists.

| Setting | Values | Default |
|---|---|---|
| `vendors.restore_resumes_fetching` | true, false | `true` |
| `export.range_basis` | detected, published | `published` |
| `fetch.robots_block_fails_immediately` | true, false | `true` |
| `churn.count_edited` | true, false | `true` |
| `vendors.name_case_insensitive` | false, true | `true` |
| `churn.trend_includes_current_month` | true, false | `true` |

## Maintenance protocol (issues and labels)

Labels are the state; GitHub is the only record. `.github/labels.yml` defines them.

1. **Pick** an open issue labelled `go` with no assignee and no `claim:*` label (or one whose
   lease comment has expired and that has no open linked PR). `p1` before `p2` before `p3`.
2. **Claim** it: a person assigns themself; an agent adds `claim:agent` and a comment
   `<!-- bears:claim lease_until=<UTC+6h> branch=<branch> -->  Working on this.` Leave issues
   with `claim:bears` or an assignee alone.
3. **Branch** from `main`: `<who>/<N>-<slug>` (bears uses `bears/<N>-<slug>`).
4. **Reproduce first:** write `tests/acceptance/test_<slug>.py` that fails on `main` for the
   reason the issue describes. If you cannot make it fail, label `cannot-reproduce`, say why in a
   comment, remove your claim, and stop.
5. **Fix** with the smallest change that makes it pass without weakening another test.
6. **Verify:** run every command in *Setup, run, test*; the whole suite must be green; the
   README's quick start must still work as written.
7. **Documents:** update this file if a command, module or convention changed; `READINESS.md`
   or `SECURITY.md` if a row changed; add a line under *Unreleased* in `CHANGELOG.md`.
8. **Open a PR** with the template (`.github/pull_request_template.md`): what and why, the
   failing test's name, the verification you ran, and `Fixes #N`. Remove your claim label; the
   PR is now the lock. **Never push to `main`. Never change `.github/workflows/` in a fix PR.**
   Never commit a secret, a database file or demo credentials.
9. The owner reviews and merges on GitHub. A release follows (`.github/bears.yml` ›
   `release.on_merge`).

bears follows exactly these steps; its comments carry `<!-- bears:… -->` markers and the PR
label `bears`. Policy for this repo: `.github/bears.yml`.

## Provenance

Generated by an autonomous software build from a short product brief, with automated checks (its tests, a walk of every documented flow, a security review and a readiness review) before release. See `NOTICE`, `LICENSE` and `READINESS.md`.
