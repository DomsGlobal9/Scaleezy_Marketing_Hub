# PRXX_SECURITY_ATTACK_MATRIX.md

Do not mark PASS from code inspection alone when an automated test is practical.

| Attack ID | Attack | Applicable? | Expected | Test/evidence | Result |
|---|---|---|---|---|---|
| TEN-01 | Tenant A references Tenant B brand | | Reject/no write | | |
| TEN-02 | Tenant A references Tenant B source | | Reject/no write | | |
| TEN-03 | Tenant A references Tenant B memory/parent | | Reject/no write | | |
| TEN-04 | Guess other tenant object ID | | 404/deny | | |
| TEN-05 | Staff without membership | | deny | | |
| BR-01 | Brand A references Brand B source in same workspace | | reject | | |
| BR-02 | PATCH only relation to create invalid final graph | | reject | | |
| RBAC-01 | Viewer mutates | | deny | | |
| LIFE-01 | Direct PATCH protected status | | reject/ignore | | |
| LIFE-02 | Invalid transition | | reject | | |
| LIFE-03 | Archived/revoked object reprocessed | | reject | | |
| IDEM-01 | Same action/job twice | | no duplicate permanent effect | | |
| INT-01 | Self-reference/supersession cycle | | reject if applicable | | |
| STATE-01 | Stub/failure reports success | | impossible | | |
| STORE-01 | Storage failure | | honest failure | | |
| URL-01 | Untrusted URL causes SSRF | | blocked/controlled | | |
| AI-01 | Provider receives wrong tenant context | | impossible | | |
