# Baseline Failures (PR 0)

## Backend Tests (`python manage.py test`)
- **Status:** **FAIL**
- **Failures:** 2
- **Notes:** The backend test suite ran and produced 2 failures:
  1. `test_missing_configuration_raises_error (apps.social_accounts.test_meta.MetaAdapterTests)`: Fails because the local `.env` now contains Meta credentials, so the test condition (empty credentials) is no longer met.
  2. `test_staff_bypass_sees_everything (apps.workspaces.tests.QuerysetScopingTests)`: Fails because the `is_staff` bypass in `WorkspaceScopedMixin` was deliberately removed earlier to fix the YouTube workspace assignment bug, but the test was not updated to reflect this security change.

## Frontend Linter (`npm run lint`)
- **Status:** **FAIL**
- **Failures:** 6448
- **Notes:** The frontend linter failed with 6456 problems (6448 errors, 8 warnings). Nearly all errors are `prettier/prettier Delete '\r'`, which indicates a mismatch between Windows CRLF line endings in the repository and Prettier's strict requirement for LF line endings. 
- **Action Required:** Either configure Git to checkout as LF (`core.autocrlf false`) or configure Prettier to ignore `endOfLine`.
