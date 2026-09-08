# PR-A: Promote the production feedback vocabulary (56 elements)

## What this unblocks

`docs/ENHANCEMENT_PLAN.md` carries an open blocker: the real 52-element feedback vocabulary was never enumerated, so Phase 6 shipped against 56 provisional placeholder rows flagged `is_provisional=True`, and the review UI says so. **This PR is the handover.** The production list exists — it is the exact chip taxonomy the Content Engine review console tags with — and it lands here as a data change, exactly as the plan designed for: no enum touched, nothing already learned is lost.

It also settles the spec discrepancy: the real count is **56, not 52**. The nine documented per-group counts (8+10+10+6+6+5+3+4+4) always summed to 56; "52" was a stale figure in early documents.

## Changes

- **`apps/feedback/vocabulary.py`** — the provisional stand-in is replaced by the authoritative `ELEMENTS` list: the console's exact chip labels, groups, ordering, and a description per element. `PROVISIONAL_ELEMENTS` is kept as an alias so migration `0002`'s import stays valid on fresh databases (it seeds the real list, still flagged provisional, and `0003` promotes it immediately after).
- **`apps/feedback/migrations/0003_production_vocabulary.py`** — idempotent promote/retire migration:
  1. Upserts all 56 authoritative elements. Rows whose keys already exist (`logo_placement`, `font_size`, `tone_of_voice`, `audience_fit`, …) keep their identity, so learned rules and recorded feedback that reference them keep resolving; label/group/description/position are realigned to production.
  2. Retires placeholders with no production counterpart by **deactivating** them — never deleting — so historical feedback tagged with them keeps resolving.
  3. Leaves untouched any non-provisional row outside the list (admin curation a migration has no business editing).
  Symmetric reverse migration included.
- **`apps/feedback/tests.py`** — `VocabularySeedTests` rewritten for the promoted state: per-group active counts (8/10/10/6/6/5/3/4/4 = 56), zero active provisional rows, production labels verbatim (`Repetitive scene`, `Looks AI / fake`), key continuity for rows learned against the placeholders, and a staged-placeholder test proving retire-by-deactivation plus reverse. The elements-endpoint test now expects `provisional: false` — the UI stops showing the stand-in notice.
- **`docs/ENHANCEMENT_PLAN.md`** — the *Blocked* section marked resolved.

## Evidence

`python manage.py test apps.feedback` (SQLite, per settings): **30/31 pass**.
The single error — `ReviewIntegrationTests.test_rejecting_twice_changes_the_next_prompt` (`ImportError: cannot import name 'genai'`) — is an environment gap (`google-genai` not installed locally) and **fails identically on the base branch**; verified by stashing this change and re-running.

## Scope discipline (AGENTS.md)

- No tenant/RBAC architecture touched. No publishing, billing, secrets, or infrastructure touched.
- No schema migration: `FeedbackElement`'s shape is unchanged; `0003` is data-only.
- The engine continues to read keys from the database — future vocabulary curation remains an admin data change, not a deploy.
