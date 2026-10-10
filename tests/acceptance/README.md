# Acceptance tests

End-to-end checks of Driftwatch: 87 file(s), each checking one thing a user, an operator or an attacker could do, through the product's real interface. The helpers in `_helpers/` drive that interface.

Run them from the repository root (they need pytest):

    python -m pytest tests/acceptance

## Known open items

These tests are marked as expected failures (`xfail`): the behaviour they check isn't there yet, so the suite stays green. Each one passes (XPASS) once it is fixed; then delete the mark at the end of its file.

- `test_backup_archives_which_hold_password_hashes_secret_key.py`: Known security issue (low): Backup archives (which hold password hashes and the secret key) are readable only by their owner
