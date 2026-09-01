# Create From Inspiration — Release Scope Decision

**Date:** 2026-09-01

**Status:** Immutable release clarification
**Applies to:** `CREATE_FROM_INSPIRATION_PREFLIGHT_2026-09-01.md`

## Decision

The production-proven first release accepts:

- uploaded JPEG, PNG, or WebP poster/screenshot references up to 15 MB;
- public HTTPS webpages whose readable text provides copy and tone direction.

It deliberately does **not** claim visual analysis for direct media URLs, videos,
audio, PDFs, presentations, or other documents. Those inputs require a vetted
normalisation adapter (for example, bounded frame extraction, page rendering, or
transcription) before they can produce grounded creative observations through the
provider-neutral AI Router. Unsupported types fail before storage or generation;
they never produce a generic poster presented as a similar result.

This clarification narrows CFI-006 in the original immutable preflight. It does not
change PR0–PR6 ownership: Inspirations owns provenance and analysis, Context owns
Brand Brain assembly, AIRouter owns provider choice, Content owns the draft, and
Review/Publishing remain the only path toward publication.

## Follow-up acceptance gate for broader types

A new type may be enabled only when it has all of the following:

1. bounded upload/fetch validation and SSRF-safe retrieval;
2. a provider-neutral normalisation contract;
3. grounded observations or an honest FAILED state;
4. tenant, brand, lifecycle, lineage, retry, and cost-safety tests;
5. no direct third-party copying and no automatic publication.
