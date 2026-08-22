# Core Recovery Integration Preflight — 2026-08-22

## Identity

- PR: P0/P1 core recovery integration
- Commit/branch at preflight: `codex/core-recovery-p0` at `0c398e0`, merging `origin/claude/scaleezy-pr6-integration-a18080`
- Authorized scope: consolidate the approved recovery work for client selection, Add Client, automatic AI readiness, editable business onboarding and Brand Master, correction propagation, Admin-only provider routing, selected-client publishing, Settings separation, and the core-loop release gate.
- Explicitly out of scope: PR7, replacement of PR0–PR6 contracts, infrastructure changes, destructive migration, and implementation of the still-open Knowledge/Inspiration analysis loops.
- Latest CTO instruction reviewed: `docs/CTO_REVIEW_LOG.md` and `docs/reviews/CORE_RECOVERY_LEDGER.md`.

## Existing architecture to reuse

| Concern | Existing implementation | Reuse decision |
| --- | --- | --- |
| Tenant/RBAC | `MarketingWorkspace`, `WorkspaceMember`, `WorkspaceScopedMixin`, `X-Workspace-Id` | Preserve; require explicit selection for multi-workspace users and membership on every request. |
| Models | `Brand` as authoritative business identity; compiled Brand Brain as derived state | Add business fields to `Brand`; never make the compiled snapshot authoritative. |
| API | DRF workspace/brand/AI routes and common response envelope | Preserve endpoints; keep selected workspace explicit and responses honest. |
| Jobs | Existing durable jobs and publishing scheduler | Preserve; no infrastructure expansion. |
| Storage | Existing content and media storage boundaries | Preserve. |
| AI/provider | Adapter registry, catalogue, `AIRouter`, capability routes | Select by capability and policy only; no product path names a vendor. |
| Frontend | TanStack hub shell, shared API client and workspace store | Use one selected-workspace source and keep AI administration in Admin. |
| Tests | Django integration/security suite plus TypeScript, ESLint and Vite gates | Extend with bootstrap, provisioning and full-lifecycle integration coverage. |

## Dependency graph

User → Auth → Workspace selector/Add Client → membership and role → default Brand → editable onboarding → authoritative Brand data → Brand Brain compiler → Context Gateway → AIRouter capability policy → durable content → Review → Publishing → return to selected-client library → isolation and regression tests.

## Entry-path matrix

| Mutation / capability | POST JSON | Multipart | PUT | PATCH | Custom action | Job/internal | Other |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Add Client bootstrap | Yes | N/A | N/A | N/A | N/A | AI provisioning | Transaction rollback on unavailable platform AI |
| Business profile / Brand Master | Yes | Logo only | Yes | Yes | Rebuild brain | Compiler/context | Same-workspace checks |
| AI provider/routing administration | Yes | N/A | Yes | Yes | Replace ordered route set | Router resolution | OWNER/ADMIN guard |
| Publishing | Yes | Existing upload path | Existing | Existing | Approve/publish | Durable publish/retry jobs | Selected workspace + content identity |

## State machine

| Object | From | Action | To | Who may perform | Invalid transitions |
| --- | --- | --- | --- | --- | --- |
| Client | absent | Add Client | workspace + OWNER + default Brand + usable AI routes | authenticated user | partial/orphan creation |
| Brand Brain | prior/empty snapshot | authoritative Brand edit or rebuild | new deterministic version | EDITOR+ | direct derived-state edits |
| Content | DRAFT | review/approval | APPROVED | authorized workspace member | direct publish from unapproved or foreign content |
| Publishing job | approved content | publish/retry | durable terminal state | authorized member/job | workspace mismatch, fake success |

## Requirement → implementation → test plan

| Req ID | Requirement | Planned code path | Planned test | Security/failure case |
| --- | --- | --- | --- | --- |
| CR-P0-01 | Select the addressed client everywhere | frontend workspace store/API header + backend workspace resolution | multi-client workspace tests and browser smoke | missing/foreign/mismatched selection fails closed |
| CR-P0-02 | Add Client is immediately usable | workspace transaction + default Brand + `provision_default_ai` | `ClientBootstrapTests` | unavailable AI returns 503 and rolls back |
| CR-P0-03 | AI administration is tool-neutral, redundant and Admin-only | adapter catalogue, ordered route sets, strategies, `/admin` | AI router/API/provisioning tests | Editor denied; invalid replacement atomic |
| CR-P1-01 | Business context is editable and influences generation | Brand fields, serializers, Brand Master/onboarding, compiler/context | Brand API/brain/context/lifecycle tests | cross-tenant data invisible |
| CR-P0-04 | Publishing addresses selected durable content | publishing UI/API and existing state machine | publishing regression suite | foreign/unapproved content rejected |
| CR-P0-05 | One complete core code path remains intact | API lifecycle integration | `CoreProductLifecycleTests` + full regression | second tenant sees no records |

## Risk scan

- Cross-tenant FK: covered by workspace scoping and lifecycle isolation assertions.
- Cross-brand FK: existing PR1 validators remain unchanged.
- Partial PATCH: Brand serializer validates the effective business profile representation.
- Direct lifecycle mutation: existing content/review/publishing transitions remain authoritative.
- Duplicate/retry: existing durable publishing tests remain in the full suite.
- Storage: unchanged.
- External URL / SSRF: unchanged by this integration.
- Provider failure: strict bootstrap rolls back; repair helper reports failure without fake readiness.
- Revocation/deletion: frozen behavior unchanged.
- Data lineage: Brand remains authoritative; brain is recompiled derived state.
- Billing/quota: unchanged and exercised by the regression suite.
- RED autonomy conditions: no frozen contract, credential semantics, publishing architecture, or infrastructure stack is replaced.

## Stop decision

- PROCEED
- Reason: the integration fills missing user-journey connections while preserving PR0–PR6 ownership. PR7 remains closed.
