# Scope: Driftwatch

Driftwatch is a self-hosted web service that a platform, security or vendor-management team runs for itself. In v1 the team registers the vendors it depends on, such as databases, identity providers and secrets managers. For each vendor it adds the public changelogs, release feeds and docs pages to watch. Driftwatch fetches those sources on a schedule and stores every new entry or page change with its original text, keeping a permanent history. Reviewers classify each change, for example as a deprecation, a default change or a narrowed scope. The team can then compare vendors by how much they churn over time and export a dated, verifiable evidence pack for one vendor before a renewal or an upgrade.

## Users

- **Admin (owner):** runs the install and manages users, vendors, sources and settings. They can do everything an analyst can. The first admin account is created on first run (see Install and run). Signs in to the web interface with a username and password.
- **Analyst:** adds and edits vendors and sources, triggers fetches, triages changes and exports evidence. Signs in with a staff account created by an admin.
- **Viewer:** an engineer or procurement person who browses history, reads the churn report and downloads evidence packs. Cannot change anything. Signs in with a staff account created by an admin.

There is no anonymous access. Every page and every export requires a signed-in user.

## Core flows

### F1: Install and first run
- Who: Admin
- Steps:
  1. The operator follows the README and runs the single install-and-start command on a fresh machine.
  2. The service creates its data directory and schema, then listens on 127.0.0.1:8080 (default).
  3. Because no users exist, opening the URL shows a one-time setup page. The operator enters the admin username and a password, entered twice. The system checks the password rules in Domain rules.
  4. The admin account is created and the operator is signed in. They land on an empty Vendors page that has an "Add vendor" button and a note naming the demo command.
  5. Optionally, the operator runs the documented demo command (for example `driftwatch demo load`) and reloads the page. Demo vendors, sources and history now appear.
- When it goes wrong:
  - The port is in use: startup exits with a message naming the port and the config variable that changes it.
  - The data directory is not writable: startup exits with the path and the reason.
  - The password is too short or the two entries do not match: the form shows an inline error and nothing is created.
  - Someone opens the setup page after an admin exists: they are redirected to sign-in.
  - The demo command is run on a system that already has vendors: it refuses, unless run with `--force-into-existing`.

### F2: Add and manage a vendor and its sources
- Who: Analyst or Admin
- Steps:
  1. The user clicks "Add vendor". They enter a name (unique), a category (database, identity, secrets, cloud infrastructure, observability, payments or other), an optional homepage URL, an optional renewal date and optional notes. Then they save.
  2. On the vendor page, the user clicks "Add source". They enter a URL and pick a source type: RSS, Atom, JSON Feed, GitHub releases (owner/repo), or HTML page (with an optional CSS selector for the changelog region). They can also pick "Auto-detect", which inspects the response content type and the feed autodiscovery links.
  3. The user clicks "Test". The system fetches the source once without saving anything and shows the detected type, the item count, and the newest 5 titles or extracted text.
  4. The user saves. The source is stored with its fetch interval (default from Domain rules, editable per source). Its baseline fetch runs immediately (see F3).
  5. Later the user can edit a vendor or source, pause or resume a source, archive a vendor, or restore an archived vendor. Archiving stops fetching and hides the vendor from the churn report, but keeps all history. Archived vendors appear under an "Archived" filter.
- When it goes wrong:
  - Duplicate vendor name: "A vendor with this name exists" is shown, with a link to it.
  - Duplicate source URL on the same vendor: the save is refused.
  - Invalid URL, or a scheme other than http or https: a field error is shown.
  - Test fetch fails (DNS, timeout, HTTP 4xx/5xx, too large): the exact reason is shown, and saving is still allowed only if the user ticks "save anyway".
  - Selector matches nothing: a warning is shown and the full page body is used unless the user corrects the selector.
  - A viewer tries to edit: the buttons are hidden, and a direct request returns "Not allowed".

### F3: Fetch sources and record changes
- Who: System (scheduler); Analyst or Admin ("Fetch now")
- Steps:
  1. The scheduler picks each active source whose interval has elapsed. A user can also click "Fetch now" on a source or a vendor.
  2. The system fetches the source within the limits in Domain rules. It stores the raw response as a snapshot with the fetch time, HTTP status and SHA-256 hash.
  3. For feeds and GitHub releases, each item not seen before (deduplication key per Domain rules) becomes a change entry. The entry holds its title, published date, link, full text and the snapshot it came from.
  4. For HTML pages, the system extracts the normalized text of the selected region and diffs it against the previous snapshot. Each added, removed or modified block becomes a change entry that holds the before and after text.
  5. Keyword rules suggest a category for each new entry (see Domain rules). The entry enters the triage queue as "unreviewed".
  6. The source page shows the last fetch time, the result, the number of new entries, and a fetch log covering the last 50 attempts.
- When it goes wrong:
  - Network or HTTP error: the attempt is logged with the reason and retried at the next interval. After 3 consecutive failures the source is marked "failing", and a badge appears on the Vendors page.
  - Unchanged content (same hash): the attempt is logged as "no change" and no snapshot is duplicated.
  - Unparseable feed: the attempt is logged as a parse error, the raw body is kept for inspection, and no entries are created.
  - "Fetch now" is clicked while a fetch of that source is running: the user sees "already fetching" and no second fetch starts.
  - Blocked by robots.txt (when `fetch.robots_txt` = respect): the attempt is logged as "blocked by robots.txt" and the source is marked failing.

### F4: Triage changes
- Who: Analyst or Admin
- Steps:
  1. The user opens the Triage queue, which lists unreviewed entries newest first. They can filter by vendor, source, suggested category and date.
  2. The user opens an entry. It shows the original text or diff, the source link, the fetch time and the suggested category.
  3. The user does one of three things:
     - Confirms or changes the category, sets an impact (low, medium or high), optionally adds a note and an "affects us" flag, and saves. The entry becomes "reviewed".
     - Clicks "Dismiss" because the entry is noise, such as typo fixes or marketing posts, and gives an optional reason. The entry becomes "dismissed".
     - Selects several entries and applies a category or a dismissal in bulk.
  4. The user can reopen any reviewed or dismissed entry. Reopening returns it to "unreviewed", and each change is kept in the entry's history with the user and the time.
- When it goes wrong:
  - Another user saved the entry since it was opened: "Changed by <user> at <time>, reload to see their version" is shown and nothing is overwritten.
  - High impact is chosen with no note: a field error is shown, because a note is required.
  - Entry not found (bad link): a 404 page with a link back to the queue.
  - Viewer: the triage controls are not shown.

### F5: Browse and search the history
- Who: Any signed-in user
- Steps:
  1. The user opens the Timeline. It lists all change entries, newest first, 50 per page.
  2. The user filters by vendor, vendor category, change category, impact, status, the "affects us" flag and a date range. They can also search the full text.
  3. The user opens an entry. It shows the full text or diff, the triage history and the snapshot. "View raw snapshot" shows the stored response exactly as fetched, with its hash.
  4. The filtered view's URL can be copied and shared with a teammate who is signed in.
- When it goes wrong:
  - A search with no results: "No changes match", with a "clear filters" action.
  - An invalid date range (start after end): a field error is shown.

### F6: Compare vendor churn
- Who: Any signed-in user
- Steps:
  1. The user opens the Churn report. It shows a table of active vendors by month for the last 12 months (default; selectable 3, 6, 12 or 24). Each cell holds the churn score from Domain rules.
  2. Each row shows the vendor's total score, its counts per category, and its trend. The trend compares the last 3 months with the 3 months before.
  3. The user sorts by total score or by any category, and filters by vendor category.
  4. Clicking a cell opens the Timeline (F5) filtered to that vendor and month.
  5. The user clicks "Export CSV" to download the table as shown.
- When it goes wrong:
  - No vendors or no entries in the period: an empty state explains that scores appear after fetches and triage.
  - Unreviewed entries in the period when `churn.count_basis` = confirmed_only: a notice gives the count of unreviewed entries that are excluded, with a link to the triage queue.

### F7: Export an evidence pack before a renewal or upgrade
- Who: Any signed-in user
- Steps:
  1. On a vendor page, the user clicks "Evidence pack". The date range defaults to the 12 months up to the vendor's renewal date, or up to today if no renewal date is set. The user can change the range, the minimum impact and the categories.
  2. The system builds a single downloadable archive containing:
     - a human-readable report (HTML) with a summary of counts by category and month, and every included entry with its original text or diff, source URL, published and fetched times, triage category, impact, notes and reviewer;
     - a CSV of the same entries;
     - the raw snapshots referenced by the entries;
     - a manifest listing each file with its SHA-256 hash.
  3. The export is recorded in the audit log with the user, the vendor, the range and the manifest hash. The vendor page lists past exports.
- When it goes wrong:
  - No entries in the range: the user is warned and can still export, producing an empty pack that states the range checked.
  - Invalid range: a field error is shown.
  - Export larger than the limit in Domain rules: the user is asked to narrow the range.

### F8: Manage users and access
- Who: Admin
- Steps:
  1. The admin opens Users and clicks "Add user". They enter a username and role. The system generates a one-time password, shows it once, and requires the new user to change it at first sign-in.
  2. The admin can change a user's role, reset a password (which issues a new one-time password), or deactivate or reactivate a user. A deactivated user's sessions end immediately.
  3. The admin can view the audit log and filter it by user, action and date.
  4. Any user can change their own password from their profile.
- When it goes wrong:
  - Duplicate username: a field error is shown.
  - Deactivating or demoting the last active admin: refused with "At least one admin is required".
  - Wrong current password on a password change: an error is shown.
  - Too many failed sign-ins: the account is locked for the period in Domain rules.

## Features
### Must have (v1)
- M1: One-command install, setup page for the first admin, and an explicit demo-data command (F1)
- M2: Vendor records with category, renewal date, notes, archive and restore (F2, F6, F7)
- M3: Source types: RSS 2.0, Atom, JSON Feed, GitHub releases, and HTML pages with a CSS selector, plus auto-detect and a test fetch (F2, F3)
- M4: Scheduler and "Fetch now" with limits, retries, failing status, a per-source fetch log and immutable stored snapshots (F3)
- M5: Change detection: new feed items by deduplication key and HTML block diffs that keep before and after text (F3)
- M6: Keyword-based category suggestion with an editable keyword list per category (F3, F4)
- M7: Triage queue with classify, impact, notes, the "affects us" flag, dismiss, reopen and bulk actions, with history per entry (F4)
- M8: Timeline with filters, full-text search and a raw snapshot view (F5)
- M9: Churn report by vendor and month with scores, trend and CSV export (F6)
- M10: Evidence pack with an HTML report, CSV, raw snapshots and a hashed manifest (F7)
- M11: Users with admin, analyst and viewer roles, one-time passwords, lockout and an audit log (F8)
- M12: Settings page for the operator settings and defaults, plus a backup and restore command (F1, F8)

### Later (not in v1)
- Email, Slack or webhook alerts on new high-impact changes: the core is the record, and alerts can be added on top of it.
- AI summarization or classification: keyword rules and human triage are enough for v1 and easier to audit.
- Headless-browser rendering for JavaScript-only pages: it is heavy to run, and most changelogs ship feeds or static HTML.
- A shared catalog of vendor source URLs: needs curation and hosting.
- SSO or OIDC sign-in: local accounts are enough for a team self-host.
- Multi-tenant hosting and a public API: the product is single-team and self-hosted.
- Tracking contract terms and renewal costs: not part of tracking changes.

## Domain rules and defaults
- **Fetching:**
  - Default interval: 6 hours (default). Allowed intervals range from 15 minutes to 7 days.
  - Request timeout: 30 s (default). Maximum response size: 5 MB (default). Redirects are followed up to 5 (default).
  - User-Agent: `Driftwatch/<version> (+self-hosted)`.
  - At most 4 fetches run concurrently (default), and at most 1 per host at a time.
  - After 3 consecutive failures (default) the source is marked "failing". The next success clears the status.
- **GitHub releases:** read through the public releases Atom feed by default. An optional GitHub token in the config raises rate limits by using the API instead.
- **Deduplication key:** feed item GUID or id. If missing, the link. If both are missing, a SHA-256 of the title and published date. An item that comes back with changed text under the same key creates a new "edited" entry that links to the original.
- **Baseline:**
  - For feeds, the first fetch imports existing items as entries marked "backfill" with their published dates. They count in churn by published date.
  - For HTML pages, the first snapshot is the baseline and creates no entries.
- **HTML diff:**
  - Text is normalized: whitespace is collapsed, and script, style and nav content is stripped.
  - Diff blocks are paragraphs, list items and headings.
  - A change of fewer than 20 characters (default) is ignored as noise but kept in the snapshot.
- **Categories:** breaking change, removal, deprecation, default change, scope narrowing, security, new capability, fix, other. The first six count as "behavior shifts".
- **Default keywords** (case-insensitive, editable):
  - deprecation: deprecat, sunset, end of life, EOL
  - removal: removed, no longer, discontinued
  - breaking change: breaking, incompatible
  - default change: default, now requires, now enabled
  - scope narrowing: limit, quota, only available, restricted, no longer supported in
  - security: CVE, vulnerability, security
  - If no keyword matches, the suggestion is "other". If several categories match, the one listed first wins.
- **Churn score per entry:**
  - Category weights: breaking 5, removal 5, scope narrowing 4, deprecation 3, default change 3, security 2, other or new capability or fix 0 (all default).
  - Impact multiplier: low ×1, medium ×2, high ×3 (default). Unreviewed entries count at ×1.
  - Dismissed entries never count.
  - An entry counts in the month of its published date, or its detection date if it has none.
- **Time:** all times are stored in UTC. Display uses the configured time zone, which is UTC (default). Month boundaries follow the display time zone.
- **Evidence pack limit:** 200 MB (default).
- **Accounts:**
  - Passwords are at least 12 characters (default).
  - 5 failed sign-ins lock the account for 15 minutes (default).
  - Sessions expire after 12 hours idle (default).
- **Retention:** snapshots and entries are kept forever (default). There is no automatic deletion.

## Operator settings

| key | values | default | what it decides |
|---|---|---|---|
| `triage.suggestions` | suggest_only, auto_apply | suggest_only | Whether keyword matches only pre-fill the category or mark the entry reviewed automatically (at low impact). |
| `fetch.robots_txt` | respect, ignore | respect | Whether fetches honor the source host's robots.txt. |
| `churn.count_basis` | include_unreviewed, confirmed_only | include_unreviewed | Whether unreviewed entries count toward churn scores. |
| `export.include_dismissed` | no, yes | no | Whether evidence packs include dismissed entries, marked as dismissed. |
| `vendors.allow_purge` | no, yes | no | Whether an admin may permanently delete an archived vendor and its history after typing its name to confirm. |

## Money and data integrity
Driftwatch handles no money, so there are no charges, payments or totals. Data integrity rules:
- **Immutable records:**
  - Snapshots and the original text of entries are never modified. Triage changes add history records instead of overwriting them.
  - Purging (only if `vendors.allow_purge` = yes) is recorded in the audit log with the counts that were removed.
- **No double-counting:**
  - The deduplication key is unique per source, so re-fetching cannot create duplicates.
  - Only one fetch per source runs at a time, enforced by a lock that survives restarts and recovers when stale (after 10 minutes, default).
- **Concurrent edits:** entries, vendors and sources carry a version number. A save made against a stale version is rejected with the message in F4.
- **Consistent counts:** churn and report counts are computed from the entries at query time, so totals always equal the sum of their entries.
- **Validation before save:** URLs, intervals within range, unique names, required notes, valid dates and role values are all checked. An entry and its snapshot reference are written in one transaction.
- **Audit log:** covers sign-ins, user changes, vendor and source changes, triage actions, exports, setting changes, demo loads, backups and restores.

## Install and run
- A single documented command installs dependencies and starts the service on a fresh machine. The README covers the prerequisites and the command.
- **Safe defaults:**
  - The service listens on 127.0.0.1:8080 unless `DRIFTWATCH_LISTEN` is set.
  - A fresh install has no users, vendors or sources.
  - The first admin is created on the setup page with an operator-chosen password.
  - There is no default password, and the session secret is generated randomly on first run if it is not configured.
- **Demo data:**
  - Loaded only by the explicit demo command.
  - Contains 8 vendors across the categories (for example a managed Postgres, an identity provider, a secrets manager), 16 sources of every type, and about 150 entries over 18 months in mixed statuses, plus 2 extra users (analyst and viewer) whose one-time passwords are printed.
  - Demo sources point at bundled fixture files served locally, so every flow works offline.
- **Configuration:** environment variables or a config file, all documented in the README: listen address and port, data directory, time zone, session secret, optional GitHub token, fetch concurrency and limits, and outbound HTTP proxy.
- **Data:** all data lives in one data directory.
  - `driftwatch backup <file>` writes a consistent archive while the service is running.
  - `driftwatch restore <file>` restores into a stopped instance.
- **Upgrades:** the schema is versioned and migrations run automatically at startup after an automatic pre-migration backup.

## Non-functional basics
- **Roles:** enforced on every request, not only by hiding buttons.

  | Action | Viewer | Analyst | Admin |
  |---|---|---|---|
  | Read history and reports, download exports | Yes | Yes | Yes |
  | Vendors, sources, fetches, triage, keyword rules | No | Yes | Yes |
  | Users, settings, audit log, purge | No | No | Yes |

- Passwords are stored with a slow salted hash. Forms carry CSRF protection.
- Every form shows clear field-level error messages.
- Persistence survives restarts. The scheduler resumes on startup.
- Outbound fetches go only to http and https URLs. Fetched HTML is shown sanitized, never executed.
- Automated tests run with one documented command. They cover each source type's parsing, deduplication, HTML diffing, keyword suggestion, churn scoring, role checks, stale-version rejection, and building an evidence pack against local fixtures.

## Definition of done
- [ ] F1: Install and first run — on a fresh machine the README command starts the service on 127.0.0.1:8080, the setup page creates the admin, the admin sees an empty Vendors page, and after the demo command the 8 demo vendors appear.
- [ ] F2: Add and manage a vendor and its sources — a new vendor with an Atom source and an HTML source passes "Test", saves, shows baseline fetch results, and can be archived and restored with its history intact.
- [ ] F3: Fetch sources and record changes — adding an item to a local fixture feed and clicking "Fetch now" creates exactly one new unreviewed entry with a suggested category, and a failing URL shows "failing" after 3 attempts.
- [ ] F4: Triage changes — an analyst classifies, dismisses, bulk-updates and reopens entries, the entry history shows each change, and a concurrent stale save is rejected.
- [ ] F5: Browse and search the history — filtering by vendor, category and date plus a text search returns the matching entries, and the raw snapshot opens with its hash.
- [ ] F6: Compare vendor churn — the report shows monthly scores matching the rules for the demo data, sorting and drill-down work, and the CSV export matches the table.
- [ ] F7: Export an evidence pack before a renewal or upgrade — the downloaded archive contains the report, CSV, snapshots and a manifest whose hashes verify, and the export appears in the audit log.
- [ ] F8: Manage users and access — an admin creates an analyst who must change their one-time password, a viewer cannot reach edit actions, and deactivating the last admin is refused.
