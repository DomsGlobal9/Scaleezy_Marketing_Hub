# Scaleezy Final Core Closure Sprint — Frozen Plan

Status: **FROZEN FOR FOUNDER REVIEW — implementation is not authorized until the founder says START.**

Baseline: `main` at `3ba4bd5` after PR0–PR7, the Super Admin/client-governance delivery, multi-entry library delivery, and mandatory universal learning.

## Decision

The old PR8–PR10 sequence is retired. It no longer matches the evolved application:

| Old item | Current decision | Reason |
|---|---|---|
| PR8 — staff SSO | Defer outside core closure | Platform authority is already explicit, database-backed and separate from Django staff/workspace RBAC. Choosing an enterprise identity provider is an authentication programme, not a missing marketing loop. |
| PR9 — payment provider/prepaid wallet | Defer to a monetisation sprint | Plans, per-capability limits, usage logs and spend caps already protect the product. Taking money requires a processor, tax/refund and reconciliation decisions and must not be mixed into intelligence recovery. |
| PR10 — mandatory cross-client learning | Complete as current PR7 | All CLIENT workspaces contribute; no consent gate, cohort floor or client opt-out. Compile, lineage, publish/retire, rank-82 injection and privacy disclosure are present. Do not rebuild it. |

The remaining work becomes one lean **Final Core Closure Sprint**, delivered as one reviewable PR with sequential vertical slices.

## Immutable architecture boundaries

1. PR0–PR7 ownership remains frozen. No tenancy/RBAC redesign, Brand Brain replacement, AIRouter bypass, publishing rewrite or PR7 reimplementation.
2. Product code stays provider-neutral. Knowledge and inspiration workflows request existing AIRouter capabilities; they never name Gemini, OpenAI, Claude or another vendor.
3. Any number of enabled providers may serve the same capability through existing ordered routes and fallback behaviour.
4. AI-derived knowledge and inspiration claims are candidates pending human review. They never silently become brand truth.
5. Confirm/reject actions remain controlled lifecycle transitions. Confirmed changes rebuild the derived Brand Brain; source provenance is retained.
6. All background work uses the existing durable job system. Requests enqueue and report `QUEUED`; they never perform long AI work inline or claim fake completion.
7. Every request and persisted object remains bound to the selected client. `X-Workspace-Id`, membership checks and same-workspace/same-brand validation remain authoritative.
8. Settings owns client preferences only. Platform controls remain in Super Admin; provider configuration remains in Admin; Brand Master owns brand intelligence.
9. Production failures fail honestly. No mock URL, fake asset, fake analysis result or success state may be persisted.

## Authorized scope

### Slice A — Knowledge processing

- Replace the Knowledge `501` process action with an idempotent enqueue operation.
- Extract usable text from existing source forms: pasted text/notes/transcripts, safe URLs already represented as sources, and supported uploaded documents.
- Use existing AIRouter `TEXT` capability to convert extracted text into structured `BrandMemory` candidates.
- Store source, provider trace, content hash, confidence and normalized key on every candidate.
- State flow: `UPLOADED → QUEUED → PROCESSING → NEEDS_REVIEW`; terminal failure is `FAILED` with a safe, visible reason.
- Repeating the same content/job must not duplicate candidates. Changed content creates a new reviewable result while preserving history.
- Confirm/reject remains human-controlled; only confirmed memories influence Brand Brain.

### Slice B — Inspiration analysis

- Replace the Inspiration `501` analyze action with an idempotent enqueue operation.
- Dispatch by media type using existing capabilities: `IMAGE_ANALYSIS`, `VIDEO_ANALYSIS`, or `TEXT` for textual/link references.
- Normalize provider output into pending AI-origin `InspirationSignal` rows through the existing reconciliation service.
- Preserve user-authored signals as authority. AI signals cannot overwrite them; conflict, confirmation, rejection and supersession rules remain intact.
- State flow: `NOT_ANALYSED → QUEUED → PROCESSING → NEEDS_REVIEW`; successful human-complete review may show `READY`; failures show `FAILED` with a retry action.
- Re-analysis refreshes the active AI inference deterministically instead of accumulating duplicates.

### Slice C — Automatic learning refresh

- When a confirmed memory or inspiration signal changes, rebuild the affected Brand Brain safely and invalidate its context version through existing seams.
- Add a durable recurring own-site refresh for approved, ACTIVE clients only.
- Run enrichment only when the normalized content hash changed and capability quota is available.
- The recurring task must be retry-safe, SSRF-safe, workspace-scoped and visible in the existing health surface.
- One provider failure may fall back to the next configured provider; exhaustion produces an honest failed state.

### Slice D — Operational truth

- Enforce saved social-account settings on every publish entry path: immediate, scheduled, retry and worker execution.
- Enforce `publishing_paused`, allowed publishing window and daily post limit server-side. `automatic_retry_enabled` must control automatic retries without blocking an explicit authorized retry.
- Make every production asset/knowledge/inspiration upload strict: storage failure returns failure and creates no usable asset row. Remove runtime reliance on mock storage URLs.
- Preserve selected-client isolation for content history, review, assets, accounts, jobs and retries.
- Keep the existing content editing, review, library/history and return journey; fix only a demonstrated broken connection in that loop.

### Slice E — Full core product loop gate

Prove one real approved client can complete:

`Add/select client → onboard business → configure one or more AI providers → ingest knowledge → review/confirm facts → add/analyse inspiration → review/confirm signals → compile Brand Brain → calibrate → generate → edit/save → review/approve → publish/schedule → record feedback → learn → return to saved content → generate an improved next output.`

Also prove a second client cannot read, mutate, publish, retry or inherit the first client's brand data, sources, signals, assets, content, accounts or jobs. Universal learned patterns may be shared only through the already-governed PR7 rank-82 path.

## Explicitly out of scope

- Staff SSO or replacing the existing login system.
- Stripe/other payment processor, prepaid wallet, tax, invoicing, refund or accounting reconciliation.
- New AI-provider-specific product logic or hard-coded provider/model defaults.
- New tenancy modes, cross-tenant request access or changes to workspace membership semantics.
- Rebuilding universal learning, changing its mandatory participation policy, or changing its rank.
- Broad UI redesign, analytics redesign, CRM/inventory integration or unrelated refactoring.
- Adding new content formats merely because a provider supports them.

## Entry paths that must agree

| Rule | Required paths |
|---|---|
| Tenant and same-brand integrity | JSON POST, multipart upload, PUT/PATCH, action endpoints, jobs, retries and internal services |
| Knowledge/inspiration idempotency | first enqueue, duplicate click, worker retry, provider fallback and manual retry |
| Publishing settings | publish now, schedule creation, due-job pickup, whole-job retry and item retry |
| Honest storage | asset upload, knowledge upload, inspiration upload and generated media persistence |
| Human authority | memory confirm/reject, signal confirm/reject, re-analysis and Brand Brain rebuild |

## Acceptance evidence

During implementation, run focused changed-module and attack-path tests. Before merge, run exactly one complete release gate:

1. Knowledge extraction success, unsupported input, provider exhaustion, duplicate retry, cross-tenant and cross-brand attacks.
2. Inspiration analysis for text/image/video, conflict with user authority, duplicate retry, archive/revoke and tenant attacks.
3. Brand Brain changes only after confirmed intelligence and remains deterministic/rebuildable.
4. Publishing settings enforced in request and worker/retry paths; no cross-client asset/account/content substitution.
5. Storage outage produces no fake URL or publishable row.
6. Two-client end-to-end core-loop test, including returning to and editing saved content.
7. Full backend regression once; frontend typecheck/build once; migration drift and Django system check once.
8. Immutable self-review with zero FAIL and zero NOT VERIFIED on mandatory gates.

## Completion rule

This sprint is complete only when the full user loop works without shell access, database edits, hidden URLs, fake controls or developer intervention. Passing isolated tests without the end-to-end loop is not completion.

Any request to add SSO, payments or a new major capability requires a new explicit contract; it does not expand this frozen sprint.
