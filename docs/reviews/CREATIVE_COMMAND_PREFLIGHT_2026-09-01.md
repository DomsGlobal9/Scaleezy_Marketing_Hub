# Creative Command — Immutable Execution Preflight

## Identity

- PR: Creative Command — inspiration and layout selection in Create Content
- Commit/branch at preflight: `719d32eb` / `feat/creative-command`
- Authorized scope: implement Slice A of
  `docs/SCALEEZY_AUTONOMOUS_SOCIAL_OS_CLOSURE.md` using the existing platform
  library, brand inspirations, Context Gateway, generation service, content
  trace and layout registry.
- Explicitly out of scope: external internet discovery adapters, engagement
  inbox, performance ingestion, monetization, autopilot, new provider
  capabilities, publishing semantics and PR0–PR7 ownership changes.
- Repository gap: `PR_EXECUTION_TASKS.md` and `API_AND_DATA_CONTRACTS.md` are not
  present. Existing endpoints/tests, `docs/ARCHITECTURE.md`, PR7 evidence and
  the closure contract above govern this slice.

## Existing architecture to reuse

| Concern | Existing implementation | Reuse decision |
|---|---|---|
| Tenant/RBAC | `get_request_workspace`, membership roles and `X-Workspace-Id` | Resolve every selection through the caller's authorized workspace. |
| Platform inspiration | `PlatformInspiration`, published gallery and adoption service | Read published entries; never copy another client's data. |
| Brand inspiration | `BrandInspiration` and retrievable `InspirationSignal` | Permit only active references owned by the selected brand/workspace. |
| Context | compiled Brand Brain + Context Gateway | Add a campaign-only creative-direction supplement; never mutate the brain. |
| Generation | sync/async provider-neutral generation through `AIRouter` | Carry the same validated selection through both entry paths. |
| Content lineage | `ContentItem.layout_config.generation_trace` | Persist a compact source snapshot and resolved focus areas. |
| Layouts | `apps.layouts` registry, preview, render and export | Use installed keys; no templates app or duplicate renderer. |
| Frontend | existing Publishing wizard and Scaleezy library components | Add one responsive selection stage inside the current flow. |

## Dependency graph

User → auth → selected workspace → default brand → published platform library /
owned active inspiration → selection validation → campaign-only creative
direction → Context Gateway brief → AIRouter → durable ContentItem → generation
trace → preview/review → later learning.

## Entry paths

| Path | Required behaviour |
|---|---|
| Sync JSON generation | Validate and apply selections; persist trace. |
| Async JSON generation | Persist validated selection snapshot in the request and apply identically in the worker. |
| Library GET | Return only published platform references allowed by universal settings. |
| Brand inspiration GET | Existing tenant/brand scoping remains authoritative. |
| Layout catalogue/preview | Existing read gates and installed registry remain authoritative. |

## Requirements and proof

| ID | Requirement | Planned path | Proof |
|---|---|---|---|
| CC-001 | Unlimited inspiration selection | Publishing wizard state and validated selection list | Frontend interaction/type/build; backend list-size/context-budget tests |
| CC-002 | Platform and brand references cannot cross tenant/brand boundaries | campaign direction resolver | cross-workspace and cross-brand API tests |
| CC-003 | Campaign-only choices do not mutate Brand Brain | resolver + generation trace | before/after brain equality test |
| CC-004 | USE/AVOID/PRIMARY/SUPPORTING and focus areas reach providers | context/generation brief | router spy test for normalized brief |
| CC-005 | Sync and async paths behave identically | generation view + worker | paired request/worker tests |
| CC-006 | Every used reference is explainable later | ContentItem generation trace | persisted provenance test |
| CC-007 | Layout is selected before generation and stored | Publishing wizard + `layout_plugin` | API persistence and frontend build tests |
| CC-008 | No configured media provider means honest partial/unavailable state | existing router semantics | provider-failure regression test |

## Risk scan

- Cross-tenant/cross-brand identifiers: highest risk; resolve server-side and
  reject the complete request on any inaccessible id.
- Context size: unlimited user selection is preserved, but raw media is not
  placed in prompts. Deterministic compact summaries include every selected
  reference and report truncation explicitly.
- External URL/SSRF: this slice displays/stores existing library metadata and
  does not fetch arbitrary URLs.
- State honesty: trace only records references successfully resolved and sent.
- Brain ownership: no write or compiler change.
- Provider/routing/billing: existing gates remain authoritative.
- Publishing: unchanged.

## Stop decision

- PROCEED
- Reason: this slice connects existing, approved modules through an additive
  campaign-level contract. It does not replace a frozen owner or add external
  network retrieval.
