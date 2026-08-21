# Baseline Failures (PR 0)

## Backend Tests (`python manage.py test`)
- **Status:** **PASS**
- **Failures:** 0
- **Notes:** The backend test suite ran successfully (290 tests) against the `default` test database. The two previous failures (`test_missing_configuration_raises_error` and `test_staff_bypass_sees_everything`) were fixed in PR0 rework. Expected RBAC rejections (e.g., `Denied by role: user=2 role=EDITOR required=ADMIN`) are properly asserted and do not cause test failures.

## Frontend Linter (`npm run lint`)
- **Status:** **FAIL**
- **Failures:** 6448
- **Notes:** The frontend linter failed with 6456 problems (6448 errors, 8 warnings). Nearly all errors are `prettier/prettier Delete '\r'`, which indicates a mismatch between Windows CRLF line endings in the repository and Prettier's strict requirement for LF line endings. 
- **Action Required:** Either configure Git to checkout as LF (`core.autocrlf false`) or configure Prettier to ignore `endOfLine`.
