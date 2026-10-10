# Assumptions

The idea this product was built from leaves these questions open. Each section says what this version does.

The rules and numbers the idea left open are set as defaults in the product scope, `SCOPE.md` (each marked *(default)*).

## Settings

Where reasonable operators differ between two business policies, the operator chooses. Each setting below exists in this version; the README's configuration section says how to change it, and the environment variable named below overrides it everywhere.

| key | values | default | scope | settles |
|---|---|---|---|---|
| `vendors.restore_resumes_fetching` | true, false | `true` | global | When an archived vendor is restored, do its sources resume fetching automatically? |
| `export.range_basis` | detected, published | `published` | global | Which date decides whether an entry falls inside an evidence pack's date range? |
| `fetch.robots_block_fails_immediately` | true, false | `true` | global | Is a source blocked by robots.txt marked failing immediately, or only after 3 consecutive failures like other errors? |
| `churn.count_edited` | true, false | `true` | global | Do 'edited' entries (same item, changed text) count toward churn as separate entries? |
| `vendors.name_case_insensitive` | false, true | `true` | global | Is vendor name uniqueness case-insensitive? |
| `churn.trend_includes_current_month` | true, false | `true` | global | Does the churn trend's 'last 3 months' include the current, partial month? |

- `vendors.restore_resumes_fetching` (`VENDORS_RESTORE_RESUMES_FETCHING`): `true`: restoring a vendor resumes fetching of its non-paused sources; `false`: restoring a vendor leaves its sources paused until resumed manually.
- `export.range_basis` (`EXPORT_RANGE_BASIS`): `detected`: entries are included by when Driftwatch detected them; `published`: entries are included by published date, falling back to detection date.
- `fetch.robots_block_fails_immediately` (`FETCH_ROBOTS_BLOCK_FAILS_IMMEDIATELY`): `true`: one robots.txt block marks the source failing; `false`: robots.txt blocks count toward the consecutive-failure threshold.
- `churn.count_edited` (`CHURN_COUNT_EDITED`): `true`: edited entries count in churn like any other entry; `false`: edited entries are shown but excluded from churn scores.
- `vendors.name_case_insensitive` (`VENDORS_NAME_CASE_INSENSITIVE`): `false`: names differing only in case are distinct vendors; `true`: names differing only in case are duplicates and refused.
- `churn.trend_includes_current_month` (`CHURN_TREND_INCLUDES_CURRENT_MONTH`): `true`: trend compares the current month and the 2 before with the 3 months prior; `false`: trend compares the last 3 complete months with the 3 before them.

## Decisions

Questions that aren't a simple switch. For each: the two ways to read it, and what this version does.

### Do the 5 failed sign-ins that cause a lockout need to be consecutive (reset by a success), or counted within a time window?

- One reading: Any 5 failures ever (no reset stated)
- The other: 5 consecutive failures since the last successful sign-in or lock expiry
- **This version: it keeps the behaviour it was built with.**

### How is the 20-character HTML noise threshold measured: per block edit distance, length difference, or total changed characters per fetch?

- One reading: Total size of the change across the page
- The other: Per block, the number of characters that differ between before and after
- **This version: it keeps the behaviour it was built with.**
