# PRXX_PREFLIGHT.md — Immutable Execution Preflight

## Identity
- PR:
- Commit/branch at preflight:
- Authorized scope:
- Explicitly out of scope:
- Latest CTO instruction reviewed:

## Existing architecture to reuse
| Concern | Existing implementation | Reuse decision |
|---|---|---|
| Tenant/RBAC | | |
| Models | | |
| API | | |
| Jobs | | |
| Storage | | |
| AI/provider | | |
| Frontend | | |
| Tests | | |

## Dependency graph
Write the actual path:
User → Auth → Workspace → Role → Brand → Entry Path → Validation → Persistence → Job/Service → State → Consumer → UI → Failure → Audit/Lineage → Tests

## Entry-path matrix
| Mutation / capability | POST JSON | Multipart | PUT | PATCH | Custom action | Job/internal | Other |
|---|---:|---:|---:|---:|---:|---:|---:|
| | | | | | | | |

## State machine
| Object | From | Action | To | Who may perform | Invalid transitions |
|---|---|---|---|---|---|
| | | | | | |

## Requirement → implementation → test plan
| Req ID | Requirement | Planned code path | Planned test | Security/failure case |
|---|---|---|---|---|
| | | | | |

## Risk scan
- Cross-tenant FK:
- Cross-brand FK:
- Partial PATCH:
- Direct lifecycle mutation:
- Duplicate/retry:
- Storage:
- External URL / SSRF:
- Provider failure:
- Revocation/deletion:
- Data lineage:
- Billing/quota:
- RED autonomy conditions:

## Stop decision
- PROCEED / STOP
- Reason:
