# PRXX_SELF_REVIEW.md — Evidence Gate

## Build identity
- PR:
- Head commit:
- Reviewer mode run after implementation: YES/NO

## Requirement traceability
| Req ID | Status: PASS/FAIL/N/A/NOT VERIFIED | Evidence | Notes |
|---|---|---|---|
| | | | |

## Dependency verification
| Dependency | Status | Evidence |
|---|---|---|
| Auth → workspace | | |
| Workspace → brand | | |
| Input → validation | | |
| Validation → persistence | | |
| Persistence → service/job | | |
| Job → honest state | | |
| State → downstream consumer | | |
| API → UI (if applicable) | | |
| Failure → user-visible/error state | | |
| Provenance/lineage | | |

## Test evidence
- Changed-module tests:
- Security/adversarial tests:
- Full backend:
- Frontend build:
- Frontend typecheck:
- Frontend lint:
- Migration check:
- Other:

## Known gaps
List ONLY explicit deferred scope. Each item must reference the future PR/contract.

## Deviations
List every deviation from approved architecture.

## Readiness
- PASS count:
- N/A count:
- FAIL count:
- NOT VERIFIED count:

PR is READY only when mandatory FAIL=0 and NOT VERIFIED=0.
