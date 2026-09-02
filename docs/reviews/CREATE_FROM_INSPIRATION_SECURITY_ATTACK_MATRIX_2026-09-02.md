# Create From Inspiration — Security Attack Matrix

| Attack ID | Attack | Applicable? | Expected | Test/evidence | Result |
|---|---|---|---|---|---|
| TEN-01 | Tenant A references Tenant B brand | Yes | Reject/no write | cross-workspace brand/reference focused tests | PASS |
| TEN-02 | Tenant A references Tenant B inspiration | Yes | Reject/no write | unavailable-reference worker/API tests | PASS |
| TEN-03 | Tenant A references Tenant B memory/parent | No | No memory/parent ID accepted | request schema/code path | N/A |
| TEN-04 | Guess another tenant inspiration ID | Yes | generic reject/no disclosure | eligible queryset scoped by workspace and exact brand | PASS |
| TEN-05 | Staff without membership | Yes | deny | inherited workspace resolution/RBAC focused suite | PASS |
| BR-01 | Brand A references Brand B inspiration | Yes | reject | exact brand validation and default-switch test | PASS |
| BR-02 | PATCH relation into invalid graph | No | immutable ID-only async request | no new PATCH path | N/A |
| RBAC-01 | Viewer requests provider spend | Yes | 403/no row | normal, READY, sync-alias, whitespace/case bypass tests | PASS |
| LIFE-01 | Direct PATCH protected status | Yes | reject/ignore | inspiration protected-field tests | PASS |
| LIFE-02 | Unsupported preprocessing transition | Yes | honest 400/FAILED | sync `ASYNC_REQUIRED`, non-poster and unsupported input tests | PASS |
| LIFE-03 | Archived/revoked object reprocessed | Yes | reject/no draft | archive and during-provider revocation tests | PASS |
| IDEM-01 | Same analysis/job twice | Yes | one provider owner/no duplicate draft | row-lock analysis claim, request CAS, atomic draft/result tests | PASS |
| INT-01 | Self-reference/supersession cycle | No | not part of this path | no supersession mutation | N/A |
| STATE-01 | Image/provider/persistence failure reports success | Yes | FAILED/no fake draft | missing-image and result-write rollback tests | PASS |
| STORE-01 | Storage/composition failure | Yes | honest failure or raw generated image retained | upload and compose-failure tests | PASS |
| URL-01 | URL causes SSRF/redirect bypass/oversize read | Yes | blocked before unsafe request/within stream cap | safe-fetch and serializer attack tests | PASS |
| AI-01 | Provider receives wrong tenant/brand context | Yes | impossible | exact workspace/brand checks and default-switch test | PASS |
| AI-02 | Reference embeds prompt injection | Yes | treated as evidence, never command | analysis instruction/policy path and prompt tests | PASS |
| COST-01 | UI starts second request while durable retry may run | Yes | retry disabled after queue ownership | frontend queued/failure state logic | PASS |
