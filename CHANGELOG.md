# Changelog

All notable changes to Driftwatch. Releases are tagged on GitHub; their notes list the merged
pull requests. Add a line under *Unreleased* in the same PR as the change.

## Unreleased

- Security (S5): data directory is 0700, database and `secret.key` 0600, backup archives are created 0600; restore keeps these modes.
- Maintenance files: issue labels, `.github/bears.yml`, `AGENTS.md`, `CLAUDE.md`, CI that runs
  AGENTS.md's commands, Dependabot for Actions, issue forms and a pull request template.

## 0.1.0 — 2026-10-10

- First release.
