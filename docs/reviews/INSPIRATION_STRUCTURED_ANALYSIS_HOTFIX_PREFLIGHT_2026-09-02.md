# Inspiration structured-analysis hotfix — immutable preflight

Date: 2026-09-02

## Scope

Repair inspiration-led generation when Gemini returns no usable creative
observations. Preserve PR0 tenancy/RBAC, PR2 inspiration provenance and review
authority, PR4 Brand Brain ownership, PR5 AIRouter ownership, and PR6 queued
generation semantics.

## Dependency graph

Saved brand inspiration → queued generation → inspiration analysis → AIRouter
→ Gemini structured response → pending AI signals → creative direction →
provider-neutral content generation → Review draft.

## Requirements and proof

- IA-001: Gemini TEXT extraction and IMAGE_ANALYSIS must enforce the supplied
  JSON schema. Prove by adapter tests that inspect `GenerateContentConfig`.
- IA-002: an empty provider analysis must never be marked READY. Prove by an
  analysis lifecycle test.
- IA-003: a previously READY inspiration with zero observations must be
  re-analyzable after this repair. Prove by a recovery test.
- IA-004: no empty analysis may proceed to poster generation or mutate Brand
  Brain. Preserve the existing worker failure test.
- IA-005: tenant scoping, routing, billing, storage, publishing and review
  contracts remain unchanged.

## Risk and stop decision

The change is inside existing provider and inspiration-analysis contracts; it
does not select a provider, weaken provenance, or invent observations. Empty
outputs fail honestly and become retryable. PROCEED.
