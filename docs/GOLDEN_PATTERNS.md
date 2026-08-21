# GOLDEN_PATTERNS.md — Scaleezy Implementation Patterns

These are architecture patterns, not copy-paste substitutes for inspecting current code.

## 1. Tenant-owned object
Every tenant-owned record must resolve to workspace; brand-scoped records must also resolve to a Brand in that workspace.

Server invariant:
`object.workspace_id == object.brand.workspace_id`

If referencing another tenant-owned object:
`child.workspace == referenced.workspace`
and, when brand-scoped:
`child.brand == referenced.brand`

## 2. Serializer relation validation
Dynamic FK querysets must be scoped using authenticated request/workspace context.
Never validate one serializer and later recreate relationships from raw `request.data`.

For PATCH, validate the EFFECTIVE final graph:
incoming value if supplied, otherwise existing instance value.

## 3. Immutable provenance
For provenance-bearing records, do not allow casual brand/source reassignment after creation.
If future transfer is required, design an explicit audited workflow.

## 4. Workspace-scoped ViewSet
Reuse `WorkspaceScopedMixin` and existing permission classes.
Do not introduce staff bypasses.
Custom actions must receive the same permission/scoping guarantees as CRUD.

## 5. Controlled lifecycle
Protected lifecycle fields are read-only through ordinary serializers.
Use explicit actions/services for meaningful transitions.
Validate allowed `from → action → to`.

## 6. Honest async/state
Queued != processing != ready.
A stub returns NOT_IMPLEMENTED/unavailable, never success.
Jobs must be retry-safe and permanent effects idempotent.

## 7. Explicit signal semantics
For InspirationSignal:
- origin is explicit: USER or AI (and future SYSTEM only if contract adds it)
- sentiment is explicit: LIKED, DISLIKED, NEUTRAL
- confidence/weight do not secretly redefine sentiment
- AI-origin records cannot silently become user-confirmed
- explicit user signal outranks AI inference later in resolution logic

## 8. Revocation eligibility
Archival/revocation does not need destructive cascade.
But downstream retrieval must be able to exclude revoked/archived provenance deterministically.

## 9. API evidence
For every mutation path test:
happy path + wrong tenant + wrong brand + insufficient role + protected-field mutation when applicable.

## 10. Fix the defect class
When one bypass is found, search every equivalent entry path and add a regression pattern, not only a one-line patch.
