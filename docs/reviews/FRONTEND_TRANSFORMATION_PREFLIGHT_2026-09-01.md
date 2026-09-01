# Scaleezy Frontend Transformation — Immutable Execution Preflight

## Identity

- PR: Scaleezy frontend transformation
- Commit/branch at preflight: `codex/platform-speed-trust`
- Authorized scope: apply the user-approved black, white and Scaleezy-lime visual system across the existing customer hub, Brand Master, publishing, authentication, legal and platform-console surfaces; use the supplied Scaleezy wordmark; preserve all current product journeys and API contracts.
- Explicitly out of scope: backend changes, migrations, tenant/RBAC changes, AI routing ownership, billing, Brand Brain semantics, publishing semantics, new workflows, provider behavior, or PR0–PR7 contract changes.
- Latest CTO instruction reviewed: `docs/CTO_REVIEW_LOG.md`; the approved user visual is `codex-clipboard-4f9401bd-61fc-4483-95b2-6f394a02f838.png` and the supplied logo is `Scaleezy logo.png`.
- Repository gap: the `AGENTS.md`-named `PR_EXECUTION_TASKS.md` and `API_AND_DATA_CONTRACTS.md` do not exist. Existing routes, shared components, `docs/ARCHITECTURE.md`, and current API consumers are the governing contracts.

## Existing architecture to reuse

| Concern | Existing implementation | Reuse decision |
|---|---|---|
| Tenant/RBAC | Existing authentication, workspace membership, selected-workspace store, `X-Workspace-Id`, hub and platform route guards | Preserve without modification. |
| Models | Existing backend models | No model or migration changes. |
| API | Existing central API client, TanStack loaders/hooks and server response contracts | Preserve request paths and response handling. |
| Jobs | Existing backend jobs | N/A; no job changes. |
| Storage | Existing storage services | N/A. |
| AI/provider | Existing AI Admin catalogue/provider/routing UI and AIRouter-owned backend | Visual changes only; preserve capability and provider behavior. |
| Frontend | TanStack Router, React shared UI primitives, hub shell, platform shell, route components | Extend shared tokens and shells so the visual system is consistent without duplicating workflows. |
| Tests | TypeScript, ESLint, Vite production build and browser interaction checks | Run focused lint/type/build plus desktop and responsive visual/interaction QA. |

## Dependency graph

User → auth → workspace/platform authority → existing route guard → existing API client → existing server state → existing route consumer → shared Scaleezy shell/primitives → responsive UI → honest loading/error/empty states → browser interaction and build evidence.

## Entry-path matrix

| Mutation / capability | POST JSON | Multipart | PUT | PATCH | Custom action | Job/internal | Other |
|---|---:|---:|---:|---:|---:|---:|---|
| Existing customer workflows | Preserved | Preserved | Preserved | Preserved | Preserved | N/A | Visual composition only |
| Existing platform workflows | Preserved | N/A | Preserved | Preserved | Preserved | N/A | Visual composition only |
| Authentication | Preserved | N/A | N/A | N/A | Existing login/signup | N/A | Branded responsive shell |

## State machine

| Object | From | Action | To | Who may perform | Invalid transitions |
|---|---|---|---|---|---|
| Existing domain objects | Existing state | Existing UI action | Existing state | Existing backend authority | Unchanged; this work must not add or bypass transitions |

## Requirement → implementation → test plan

| Req ID | Requirement | Planned code path | Planned test | Security/failure case |
|---|---|---|---|---|
| UI-001 | Use the supplied Scaleezy wordmark and exact lime on black/white | optimized public asset, brand logo component, global tokens | asset inspection and production build | Logo must retain aspect ratio and remain legible on dark surfaces |
| UI-002 | Match the approved editorial cockpit direction | hub/platform shells, overview route, shared primitives | same-state visual comparison | No invented counts or success states |
| UI-003 | Apply the system consistently across existing modules | shared UI components plus customer/platform/auth/legal routes | focused lint/typecheck and route inspection | Existing actions, links, tabs and error states must remain functional |
| UI-004 | Preserve responsive usability | shell navigation, horizontal tab overflow, table/filter responsiveness, touch targets | desktop/mobile browser checks | No hidden primary actions or inaccessible navigation |
| UI-005 | Preserve frozen architecture and product behavior | frontend-only change set | git diff review and production build | No backend, migration, API-contract, RBAC or provider ownership change |

## Risk scan

- Cross-tenant FK: no data relationship changes; selected-workspace behavior remains authoritative.
- Cross-brand FK: no new identifiers or persistence paths.
- Partial PATCH: existing mutation functions remain unchanged.
- Direct lifecycle mutation: unchanged.
- Duplicate/retry: unchanged.
- Storage: only a static logo asset is added.
- External URL / SSRF: no new external fetch path.
- Provider failure: existing honest UI states remain in place.
- Revocation/deletion: existing auth/route guards remain live.
- Data lineage: no learning or Brand Brain state changes.
- Billing/quota: existing API values remain authoritative.
- RED autonomy conditions: none; architecture, authority, product semantics and infrastructure remain frozen.

## Stop decision

- PROCEED
- Reason: this is a frontend-only presentation and responsive-usability transformation built on existing routes, data consumers and authority boundaries.
