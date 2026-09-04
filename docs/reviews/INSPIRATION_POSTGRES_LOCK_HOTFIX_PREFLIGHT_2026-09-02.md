# Inspiration PostgreSQL Lock Hotfix — Immutable Preflight

Date: 2026-09-02
Scope: repair final persistence for inspiration-guided generation after PostgreSQL rejected `FOR UPDATE` on the nullable `BrandSource` join.

## Dependency graph

`generate_content` → final tenant/brand/reference revalidation → row locks → draft/result persistence → Review polling.

## Entry paths

- PASS — async inspiration generation is the affected entry path (`generate-async` → worker → `generate_content`).
- N/A — ordinary generation without inspiration preprocessing does not execute this lock path.
- N/A — no API, tenancy, RBAC, Brand Brain, AIRouter, publishing, schema, or credential contract changes are required.

## Requirements and evidence plan

- The final reference lock must not contain a nullable outer join. Evidence: focused SQL-shape regression test.
- Inspiration and non-null provenance-source rows must both be locked before persistence. Evidence: exact helper path plus focused lifecycle tests.
- Archived/revoked references must still prevent draft persistence. Evidence: existing revocation test and new source-lock coverage.
- Existing generation behavior must remain unchanged. Evidence: focused module tests followed by the full backend gate.

## Risks

- PostgreSQL-specific failure is not reproduced by SQLite because SQLite omits `FOR UPDATE`; the regression therefore asserts the generated lock-query shape contains no join.
- Splitting the lock into two reads must not weaken source revocation protection; source rows are explicitly locked and checked inside the same transaction.

