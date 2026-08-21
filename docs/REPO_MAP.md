# REPO_MAP.md — Scaleezy Fast Navigation

This is a navigation accelerator, not a replacement for inspecting live code.

## Repository roots
- Backend: `Marketing_backend/`
- Backend apps: `Marketing_backend/apps/`
- Frontend: `Marketing_Frontend/`
- Governance: root `AGENTS.md`, `docs/`

## Core backend domains confirmed on current branch
- AI routing/providers: `Marketing_backend/apps/ai/`
- Analytics: `Marketing_backend/apps/analytics/`
- Audit: `Marketing_backend/apps/audit/`
- Billing: `Marketing_backend/apps/billing/`
- Brands: `Marketing_backend/apps/brands/`
- Shared tenancy/RBAC: `Marketing_backend/apps/common/`
- Content/revisions: `Marketing_backend/apps/content/`
- Feedback/training legacy: `Marketing_backend/apps/feedback/`
- Jobs: `Marketing_backend/apps/jobs/`
- Knowledge (PR1): `Marketing_backend/apps/knowledge/`
- Layouts: `Marketing_backend/apps/layouts/`
- Social/publishing-related apps: inspect existing `apps/social_*` / marketing domains before changing.

## High-value files
- Workspace queryset scoping: `Marketing_backend/apps/common/mixins.py`
- RBAC/permission patterns: `Marketing_backend/apps/common/permissions.py`
- Shared regression tests: `Marketing_backend/apps/common/tests.py`
- PR1 knowledge patterns: inspect `Marketing_backend/apps/knowledge/models.py`, `serializers.py`, `views.py`, `tests.py`, `urls.py` before PR2.
- Brand root: inspect `Marketing_backend/apps/brands/models.py`.
- Project config/routes: under `Marketing_backend/scaleezy_backend/`.

## Rules
Never guess a path from this map if it has changed. Inspect live repository first.
When a reusable pattern is discovered, update this map only if the location/purpose is stable.
