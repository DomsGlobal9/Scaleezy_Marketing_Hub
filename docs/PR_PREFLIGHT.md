# PR_PREFLIGHT.md

Complete before writing code.

## PR
- PR number/name: PR1 Rework - Knowledge Foundation Isolation
- Authorized scope: Add validation, strict isolation, read-only lifecycle fields, revoke actions, and negative tests for `apps.knowledge`.
- Explicitly out of scope: Full memory extraction logic, embeddings, frontend UI changes.

## Existing architecture reused
- Existing models: `Brand`, `MarketingWorkspace`, `WorkspaceMember`, `User`
- Existing services: `SupabaseStorageService`
- Existing permissions/RBAC: `WorkspaceScopedMixin`, `get_request_workspace`, `IsWorkspaceMember`, `HasWorkspaceRole`
- Existing jobs: `@task` from `django.tasks`
- Existing APIs: DRF ViewSets
- Existing UI patterns: N/A
- Existing tests: Django `TestCase` and DRF `APIClient`

## Files/modules likely affected
- Backend: `apps/knowledge/serializers.py`, `apps/knowledge/views.py`, `apps/knowledge/tasks.py`
- Frontend: N/A
- Migrations: N/A
- Tests: `apps/knowledge/tests.py`
- Docs: `docs/CTO_REVIEW_LOG.md`, `docs/SECURITY_ATTACK_CHECKLIST.md`, `docs/PR_SELF_REVIEW.md`

## Dependency chain
Describe:
User → Auth → Workspace → Role → Brand → Input (File Upload/Text) → Validation (Cross-tenant/Cross-brand prevention) → Persistence (BrandSource/BrandMemory) → Job/Service (Stubbed tasks) → State (PROCESSING) → Downstream (Context) → UI → Failure → Audit/Lineage → Tests

## Security boundaries
- Tenant-owned objects: `BrandSource`, `BrandMemory`
- Cross-workspace FK risks: Prevented via `validate()` checking `workspace_id`.
- Cross-brand FK risks: Prevented via `validate()` checking `brand_id`.
- Writable lifecycle fields: None (status and permanence are read-only).
- Secrets/provider credentials: N/A (Stubbed processing).
- Storage access: `SupabaseStorageService` validates prefix and workspace ID.

## State transitions
List every state and allowed transition.
- Source: UPLOADED -> PROCESSING (via `/process/` stub task).
- Source: Any -> ARCHIVED (via `/revoke/` action).
- Memory: CANDIDATE -> CONFIRMED (via `/confirm/` action).
- Memory: CANDIDATE -> REJECTED (via `/reject/` action).

## Failure scenarios
At minimum:
- invalid input: 400 Bad Request
- no permission: 403 Forbidden
- wrong tenant: 400 Bad Request / 404 Not Found
- wrong brand: 400 Bad Request
- missing dependency: 500
- provider/storage failure: 502 Bad Gateway
- job retry: N/A
- duplicate request: Idempotent processing check.
- partial failure: Avoided via transactions where applicable.

## Tests required
- Unit: N/A
- API: ViewSet behavior and Upload endpoint.
- Tenant isolation: Tests confirming users in Workspace B cannot access/mutate Workspace A objects.
- Role/RBAC: Tests confirming VIEWERS cannot create/upload sources.
- State transitions: Tests confirming `/process/`, `/confirm/`, `/reject/` work.
- Retry/idempotency: N/A
- Regression: Full suite run to confirm 0 breakages.

## Potential conflicts
List any mismatch between blueprint and existing repo.
- Fake `resolve_conflict` action was removed per CTO review, as semantics do not exist yet.

## Stop decision
If any RED autonomy condition is triggered, stop and report before coding.
- None triggered.
