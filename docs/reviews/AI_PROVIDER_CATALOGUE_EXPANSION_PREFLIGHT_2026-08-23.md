# AI Provider Catalogue Expansion Preflight — 2026-08-23

## Identity

- PR: P0 Admin provider catalogue completion
- Commit/branch at preflight: `codex/core-recovery-p0` at `8a4b7ff`
- Authorized scope: make the live Add provider workflow useful by installing additional production provider adapters that can participate in the existing capability-based routing and unlimited ordered redundancy sets.
- Explicitly out of scope: PR7, provider selection inside product workflows, user-defined network endpoints, changes to AIRouter ownership, credential semantics, tenant/RBAC rules, or Knowledge/Inspiration P1 loops.
- Latest CTO instruction reviewed: `docs/CTO_REVIEW_LOG.md`, `docs/reviews/CORE_RECOVERY_LEDGER.md`, and the live empty Add provider state supplied by the product owner.

## Existing architecture to reuse

| Concern | Existing implementation | Reuse decision |
| --- | --- | --- |
| Tenant/RBAC | Workspace-scoped provider APIs with OWNER/ADMIN enforcement | Preserve unchanged. |
| Models | Global `AIProvider` catalogue plus per-workspace encrypted configuration | Preserve unchanged; no migration. |
| API | Catalogue and workspace provider endpoints | Preserve unchanged. |
| AI/provider | Recursive adapter registry, deploy-time catalogue sync, `AIRouter` | Add adapters only; product code remains vendor-neutral. |
| Frontend | Catalogue-backed Add provider dialog | Preserve unchanged; new installed adapters appear automatically. |
| Tests | Adapter HTTP mocks and catalogue sync tests | Add focused protocol, sanitisation, discovery, and metadata coverage. |

## Dependency graph

Admin → authenticated selected workspace → ADMIN role → global installed catalogue → workspace encrypted key/model → capability route set → AIRouter → provider adapter → normalised content result → usage/failure log.

## Entry-path matrix

| Mutation / capability | POST JSON | PUT/PATCH | Custom action | Deploy/internal |
| --- | ---: | ---: | ---: | ---: |
| Add workspace provider | Existing | Existing | N/A | N/A |
| Save key/model/enable | N/A | Existing | connection test | N/A |
| Expand catalogue | N/A | N/A | N/A | idempotent `sync_ai_catalogue` |
| Route multiple providers | replace-set | N/A | atomic route replacement | AIRouter resolution |

## State machine

| Object | From | Action | To | Who may perform | Invalid transitions |
| --- | --- | --- | --- | --- | --- |
| Installed integration | adapter absent | deploy adapter + sync | catalogue available | platform deploy | arbitrary runtime endpoint creation |
| Workspace provider | catalogue only | add + key + enable | connected/enabled | OWNER/ADMIN | duplicate provider in one workspace |
| Capability route | ordered set | replace atomically | new ordered set | OWNER/ADMIN | unsupported/disabled provider |

## Requirement → implementation → test plan

| Req ID | Requirement | Planned code path | Planned test | Security/failure case |
| --- | --- | --- | --- | --- |
| AI-P0-01 | Add provider must offer more than the two original integrations | install Groq, Mistral, DeepSeek, OpenRouter, and Together adapters | registry/catalogue discovery test | no user-controlled base URL |
| AI-P0-02 | No product workflow is tied to a provider | existing capability route/AIRouter | existing AI routing suite | vendor code stays inside adapters |
| AI-P0-03 | Multiple providers may serve Copy in ordered redundancy | each adapter declares `TEXT` | catalogue metadata test + existing replace-set tests | unsupported capabilities cannot be routed |
| AI-P0-04 | Credentials and failures remain safe | existing encrypted workspace credential + sanitised adapter errors | mocked auth/transport tests | no key/upstream body returned or logged |

## Risk scan

- Tenant/RBAC: unchanged; all workspace configuration remains scoped and ADMIN-only.
- Credential handling: unchanged; plaintext is write-only and encrypted at rest.
- SSRF: no user-provided base URL is accepted; every endpoint is a code-owned HTTPS constant.
- Default tenant routing: new text adapters remain more expensive than existing defaults, so catalogue expansion cannot silently reroute new or existing tenants.
- Provider failure: adapter errors are sanitised and AIRouter keeps existing failover semantics.
- Frozen contracts: AIRouter, Context Gateway, provider models and product call sites remain unchanged.

## Stop decision

- PROCEED
- Reason: this completes the already-approved provider catalogue seam by adding replaceable adapters without altering PR0–PR6 ownership or starting PR7.

