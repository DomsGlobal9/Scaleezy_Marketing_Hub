# Create Studio Overhaul — Immutable Execution Preflight

## Identity

- Workstream: Create Studio explicit creative-source overhaul
- Branch: `codex/create-studio-overhaul`
- Base at preflight: `1284dba6`; release commit/PR pending
- Authorized scope: remove template choice from Brand Master/Brand Brain; require an explicit per-content creative mode; preserve upload, inspiration, generation, review and regeneration paths; improve the Create Studio UI without changing PR0–PR6 ownership.
- Explicitly out of scope: new provider architecture, new layout engine, publishing architecture changes, destructive removal of the compatibility database column, PR7 intelligence changes.
- Governing instruction: no template may be selected from a Brand/default preference. A user may choose a catalogue template, provide a reference, or explicitly delegate an original design for that content item.

## Existing architecture reused

| Concern | Existing implementation | Decision |
|---|---|---|
| Tenant/RBAC | workspace header, membership roles, workspace-scoped viewsets | Reuse; no bypass |
| Brand intelligence | Brand Brain compiler + Context Gateway | Keep ownership; remove only template preference input |
| Creative references | Brand/Platform Inspiration records and signals | Reuse IDs, eligibility, provenance and revocation rules |
| AI | Context Gateway → AI Router → provider adapters | Reuse; creative mode is provider-neutral |
| Content | `ContentItem.layout_plugin/layout_config` | Store choice per content/revision |
| Jobs | durable generation request/result worker | Revalidate queued choices before spend |
| Layouts | existing catalogue, preview, render and export | Reuse; require an explicit layout where a catalogue template is requested |
| Frontend | Publishing/Create flow and Poster Studio | Consolidate into Create Studio; retain every reachable input path |

## Dependency graph

User → Auth → selected Workspace → membership Role → active Brand → Create Studio entry path → creative-mode/tenant/lifecycle validation → quota/approval gate → durable request → Context Gateway → AI Router → provider → ContentItem + provenance → optional composition → Review/edit revision → publishing.

## Creative-mode contract

| Mode/path | Required input | Forbidden input | Composition ownership | Persistence |
|---|---|---|---|---|
| `AI_ORIGINAL` | explicit user choice (or explicitly enabled Autopilot mission) | catalogue layout and inspiration selections | Scaleezy chooses for this item only | mode on ContentItem/revisions |
| `CATALOG_TEMPLATE` | poster + installed layout | reference/upload input; video/carousel | exact selected layout | mode + layout on ContentItem/revisions |
| `REFERENCE` | eligible selected reference or uploaded reference | catalogue layout | original composition informed by reference | mode + reference lineage on ContentItem/revisions |
| Finished-media upload | media file | AI-generation claim | no generated composition | existing asset/content workflow |

`Brand.layout_preference` remains temporarily readable for schema compatibility only. It is read-only, absent from Brand Brain/Context, and must never be consulted by generation, preview, render, export or regeneration.

## Entry-path matrix

| Capability | JSON/API | Multipart/link | Job/internal | Review/revision | UI |
|---|---|---|---|---|---|
| New generation | sync + async endpoints | uploaded reference | worker revalidation; Autopilot explicit delegation | N/A | Create Studio |
| Reference intake | saved Inspiration IDs | upload and public HTTPS page | analysis before generation | revoked sources become ineligible | inspiration picker/add flow |
| Template composition | preview/render/export actions | N/A | post-generation compose | choice travels into revision | catalogue + Poster Studio |
| Brand mutation | serializer PATCH/PUT | logo path unaffected | compiler ignores legacy field | N/A | no Brand Master template control |

## Requirement → implementation → proof plan

| ID | Requirement | Planned paths | Required proof |
|---|---|---|---|
| CS-01 | No automatic Brand/default template | brand serializer/compiler/context; layout services/views | no-fallback tests + Brand Brain assertion |
| CS-02 | Explicit mode on every new AI request | sync/async API + Create Studio | three-mode positive/negative matrix |
| CS-03 | Template is poster-only and exact | resolver, worker, composer | missing/invalid/template-render tests |
| CS-04 | References remain tenant-, brand- and lifecycle-safe | resolver, queued worker, regeneration | cross-tenant and revoked-reference tests |
| CS-05 | Choice and lineage survive review revisions | request-edits + regeneration | provenance-carry and restyle tests |
| CS-06 | No orphaned or unreachable existing flow | Create Studio, upload/link, saved gallery | UI flow/build evidence |
| CS-07 | Failures are stage-honest and do not invite duplicate spend | request/result/composition states + poller | provider/queue/composition failure tests |

## Risk scan

- Cross-tenant/cross-brand IDs: resolve only inside selected workspace and active brand.
- Role: existing Editor-or-higher generation/layout permissions remain authoritative.
- Retry/idempotency: a durable paid generation must not be reported as safely retryable merely because composition failed.
- Storage: preserve the raw generated asset when a derived composition cannot be stored.
- External URL/SSRF: retain public-HTTPS validation and redirect revalidation.
- Revocation: re-resolve references both in queued generation and regeneration before provider spend.
- Lineage: copy creative direction to revisions; never copy a generation trace as if it were new evidence.
- Billing: quota/approval checks remain before provider dispatch.
- Migration: no schema change; compatibility column retained.

## Stop decision

- PROCEED within this contract.
- STOP if implementation restores a Brand/default template, weakens tenant/RBAC/revocation checks, hides an already-created paid draft, or changes provider/publishing ownership.
