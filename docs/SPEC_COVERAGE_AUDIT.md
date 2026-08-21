# Content Engine v2 — Spec Coverage Audit

Checked on 2026-08-21 against `Content_Engine_v2_Complete_Package.zip` (Desktop copy, byte-identical
to the Downloads copy) and `table_1787293262.csv`.

**Verdict: 10 of 12 spec areas are incorporated. Two are deliberate divergences, one area
(deployment) is genuinely absent, and one prototype feature was dropped on purpose.**

---

## 1. CSV manifest check

Every size in the CSV matches the real file exactly. But the manifest is **incomplete** — it lists
11 entries where the zip holds 12 files:

| Missing from CSV | Size | Note |
|---|---|---|
| `content-engine-app/README.md` | 893 B | Prototype quick-start |
| `content-engine-app/SPECIFICATION.md` | 54,771 B | **Byte-identical duplicate** of `01-SPECIFICATION.md` |

The duplicate matters: the package ships the same 54 KB spec twice under two names. If they ever
diverge, there is no way to tell which is authoritative.

**The zip also promises three folders it does not contain.** `content-engine-app/README.md` lists
`assets/`, `carousel/` and `showcase/`; only `app/`, `engine-code/`, `creative-brain/`, `setup/`
and `daily/` are present. So the sample logos, hero photos, generated carousels and showcase
posters referenced by the prototype are not in the package.

---

## 2. Coverage against the specification

| # | Spec area | Status | Where it lives |
|---|---|---|---|
| 1 | Multi-tenant design | **Divergent (deliberate)** | Row-scoped by workspace + enforced auth, not schema-per-tenant |
| 2 | Subscription tiers | **Done** | `apps.billing` — `Plan`, `Subscription`, `quota.py` |
| 3 | Modular plugin system | **Mostly done** | AI adapters, 6 layout patterns, export presets. No caption plugins |
| 4 | Multi-AI integration | **Exceeded** | `apps.ai` — open-ended registry, not a fixed five |
| 5 | Training & learning | **Done** | `apps.feedback` — 56 elements, `embeddings.py`, `training.py` |
| 6 | Frontend review dashboard | **Done** | `/review` route with tabs, notes, approve/reject/request-edits |
| 7 | Backend API & workers | **Divergent (deliberate)** | Django + DRF, not FastAPI. Django Tasks API, not Celery |
| 8 | Database schema | **Done** | All 7 core tables have equivalents (below) |
| 9 | Deployment guide | **Missing** | No Dockerfile, compose, K8s manifests or CI |
| 10 | API reference | **Done** | JWT auth, documented endpoints, `APIResponse` envelope |
| 11 | Security & compliance | **Done** | RBAC, Fernet-encrypted tokens, audit trails, tenant isolation |
| 12 | Vector DB | **Divergent** | JSON embeddings + in-process cosine, not Pinecone/Weaviate/pgvector |

### The spec's 7 core tables

| Spec table | Project model |
|---|---|
| `tenants` | `MarketingWorkspace` |
| `users` | Django `User` + `WorkspaceMember` (roles) |
| `brands` | `Brand` |
| `content_items` | `ContentItem` |
| `feedback` | `Feedback` + `FeedbackElement` |
| `subscriptions` | `Subscription` + `Plan` |
| `usage_logs` | `AIUsageLog` |

All seven are present.

---

## 3. Where we deliberately diverged

These are decisions, recorded in `ENHANCEMENT_PLAN.md`, not oversights.

**Django instead of FastAPI.** The spec assumes FastAPI throughout. Porting would have cost weeks
and discarded the working OAuth stack for four platforms. Every capability in the spec turned out
to be achievable in Django.

**Row-scoped tenancy instead of schema-per-tenant.** `customer_id` already implies the parent
Scaleezy system owns real tenancy. Schema-per-tenant in Django needs `django-tenants` and
complicates every migration. Isolation is enforced instead by `WorkspaceScopedMixin` +
`IsWorkspaceMember`, verified by a dedicated cross-tenant test suite.

**Django Tasks API instead of Celery + Redis.** Same durability, one less service and no broker.
Needs a worker process in deployment.

**JSON embeddings instead of a vector database.** At this row count an in-process cosine scan over
one workspace beats a network round trip, and it keeps the test suite running on SQLite.
`apps.feedback.embeddings` is the only module that knows the representation, so swapping in
pgvector later is a one-file change.

---

## 4. Genuinely not incorporated

**Deployment, entirely.** Spec section 10 covers Docker Compose, Kubernetes manifests and a GitHub
Actions pipeline. None exists — no `Dockerfile`, no `docker-compose.yml`, no `.github/workflows`,
no `k8s/`. This is the one substantial spec area with zero coverage.

**Caption plugins.** The spec's `plugins/caption/` tree — `viral_hook`, `scene_led`,
`cta_optimizer`, `hashtag_engine` — was not built. Captions come from the AI `TEXT` capability
instead, which is a reasonable substitution but not the same thing: those four are *prompting
strategies* a user could choose between, and today there is one implicit strategy.

**The prototype's Google Form feedback loop** (`setup/google-form-template.md`) was intentionally
dropped. Feedback is captured in-app on the review screen, which supersedes it.

---

## 5. The 52-element vocabulary discrepancy — resolved

I flagged during planning that `CREATIVE_BRAIN.md` claims "52 elements, 9 groups" while its own
group counts sum to **56**. The implementation followed the group counts and seeded **56** elements:

```
TYPOGRAPHY 8 · COPY 10 · LINE_BY_LINE 10 · LOGO 6 · VISUAL 6
LAYOUT 5 · AUDIO 3 · FORMAT 4 · STRATEGY 4        = 56
```

That is the right call — the per-group numbers are the specific claim, "52" is the round one. Worth
confirming with whoever wrote the document, since the element *names* were never published and had
to be authored from the group definitions.

---

## 6. Test suite state

**290 tests, 0 failing.**

The two previously failing tests have been addressed in PR0:
1. `test_missing_configuration_raises_error`: Now correctly uses `@override_settings` to remain environment-independent.
2. `test_staff_does_not_bypass_tenant_isolation`: Now explicitly asserts that staff users do *not* bypass workspace scoping (they see 0 workspaces by default).

---

## 7. Recommendation

The spec is substantially incorporated. The gap worth closing is **deployment** — everything is
running on a dev server against a live Supabase instance, with no container, no CI and no
reproducible environment. That is the thing standing between this and being shippable, and it is
also what Google and Meta app review will eventually need to see behind a stable URL.
