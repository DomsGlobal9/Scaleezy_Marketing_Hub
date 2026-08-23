# Core Product Recovery Ledger

Mission authority: `SCALEEZY_MASTER_ARCHITECTURE.md` and the approved Core Recovery handoff supersede the former PR2-only execution mission for this recovery. PR0–PR6 ownership remains frozen. PR7 is out of scope.

Statuses are evidence-based: **PASS**, **FAIL**, **BLOCKED**, or **N/A**.

| Lifecycle step | Severity | Status | Live evidence | Frozen owner | Smallest compatible recovery | Required proof |
| --- | --- | --- | --- | --- | --- | --- |
| Select/switch client | P0 | PASS | Active-client selector persists context; API calls send `X-Workspace-Id`; local browser smoke created and switched between two clients without stale UI state. | PR0 | Completed compatibly. | Frontend build, isolation tests, and two-client browser smoke passed. |
| Add Client | P0 | PASS | Client creation atomically creates OWNER membership, default Brand and initial AI routing, then enters Brand Master onboarding. | PR0/PR5 | Completed compatibly. | Bootstrap success/readiness/rollback tests and live browser creation of two clients passed. |
| Tenant AI readiness | P0 | PASS | `provision_default_ai` is called inside the workspace bootstrap transaction and provisions capability routes from the installed platform catalogue. | PR5 | Completed compatibly. | New-client readiness and rollback tests passed. |
| AI administration and redundancy | P0 | PASS | AI controls live only under `/admin`; provider-neutral ordered route sets support failover/best-of/round-robin; backend permissions and a frontend route guard enforce OWNER/ADMIN access. | PR5 | Completed compatibly. | Admin/non-admin, ordered-route, atomic replacement and router strategy tests passed; Owner/Editor browser smoke passed. |
| Workspace request isolation | P0 | PASS | Frontend sends explicit workspace context and the server rejects missing, mismatched and foreign workspace/object combinations once selection is required. | PR0 | Completed compatibly. | Isolation suite and two-client browser switch passed. |
| Durable create/edit/library/return | P0 | PASS | Generation persists provider-neutral `ContentItem` records; publishing/review use the same durable item and enforce state transitions. | PR6/existing content | Completed compatibly. | Content, marketing, review and publishing integration tests passed in the 646-test suite. |
| Publishing selected-client isolation | P0 | PASS | Publishing jobs carry workspace and durable content identity; request/job/retry paths enforce membership, state and workspace consistency. | Existing publishing | Completed compatibly. | Publishing isolation, approval-gate, retry and idempotency tests passed. |
| Knowledge processing | P1 | FAIL | Architecture and UI state automatic processing/analysis is unavailable; processing action must be inspected for current 501/task behavior. | PR1/PR6 integration | Connect supported extraction through AIRouter/jobs with honest lifecycle and retry. | Success/failure/retry/provenance tests. |
| Inspiration analysis | P1 | FAIL | UI explicitly says automatic analysis unavailable; backend contract historically returned 501. | PR2/PR6 integration | Analyze through AIRouter while preserving advisory origin and provenance. | Status/origin/isolation/retry tests. |
| Rich business onboarding / Brand Master | P1 | PASS | Onboarding and Brand Master edit the authoritative business profile, products/services, audience, social links, location and tone through the existing Brand API. | PR5/PR6 | Completed additively without changing ownership. | Brand API round-trip, compiler/context and core lifecycle tests passed. |
| Brand Brain correction | P1 | PASS | Editing an authoritative Brand field recompiles the derived brain; the version and later generation context change together. | PR4 | Completed through source-owned records; derived state remains read-only. | `CoreProductLifecycleTests.test_a_new_tenant_goes_from_signup_to_a_generated_result_unaided` passed. |
| Calibration and learning | P1 | NOT VERIFIED | PR6/learning modules and tests exist; full later-generation influence needs proof. | PR3/PR6 | Repair only broken continuity or client scoping. | Two-client influence/non-contamination test. |
| Settings boundary | P1 | PASS | Settings contains workspace, access, plan and security only; AI credentials/routing are absent and live in the guarded Admin module. | PR6 | Completed compatibly. | Settings/Admin browser boundary smoke passed. |
| Full core loop | P0 | BLOCKED | The complete code path, tenancy, RBAC, durable media, review/publish integrity and provider redundancy contracts pass together. The Render blueprint now defines one durable `run_tasks` worker with shared production secrets and graceful shutdown; production sync and a live job have not yet been observed. | Cross-cutting | Sync the approved worker without changing PR0–PR6 ownership; keep PR7 closed. | Final 690-test backend suite and frontend gates passed. Confirm the worker is live, then run one credentialed AI generation and one connected social publish smoke. |

## Recovery log

Update this section after each vertical slice with named tests and exact results. A code path without executed evidence remains NOT VERIFIED.

### 2026-08-22 — AI administration correction

- Root cause recorded: the recovery audit treated the first route row as the whole configuration even though the frozen PR5 contract is an ordered route set. The previous gap list named "provider overrides" but omitted two non-negotiable acceptance criteria: admin-only placement and multiple providers per capability.
- Corrected contract: product features request capabilities only; adapters contain vendor-specific integration; `AIRouter` owns selection, redundancy and strategy; workspace admins alone control enablement, credentials and route sets.
- Implemented: admin-only catalogue/provider/route APIs; ordered multi-provider route-set editor; atomic set replacement; provider-neutral foreground/background generation; provider-neutral image analysis, image captioning and video analysis; neutral `/api/marketing/ai-generation/` product endpoint with the old vendor path retained only as a compatibility alias.
- Evidence at that checkpoint: production frontend build **PASS**; Python compilation of every touched AI/backend module and migration **PASS**; active-path source scan for direct vendor-service calls and vendor-named product endpoints **PASS**. The temporary dependency-install block was later cleared; the complete executed result is recorded below.

### 2026-08-22 — P0 verification gate

- Backend: `manage.py check` **PASS**; `makemigrations --check --dry-run` **PASS**; migrations applied cleanly; complete Django suite **646 passed, 0 failed** in 586.873 seconds.
- Frontend: production build **PASS**; targeted substantive ESLint for every touched P0 frontend file **PASS**. The repository-wide lint command still reports the pre-existing CRLF/Prettier baseline and is not a P0 regression.
- Live browser: authentication **PASS**; two Add Client bootstraps **PASS**; selector switch between `P0 Alpha Client` and `P0 Beta Client` **PASS**; Admin provider/routing UI for Owner **PASS**; Settings contains no AI controls **PASS**; runtime console errors **0**.
- Access-control defect found and fixed during the gate: an Editor navigating directly to `/admin` could briefly render the empty Admin shell while its API calls were denied. The route now resolves the active-workspace role before rendering and redirects non-OWNER/non-ADMIN users to Overview. Editor denial and Owner access both re-verified in the browser; production build and targeted lint remain **PASS**.
- Provider neutrality/redundancy: capability-based route sets, ordered multi-provider membership, failover/best-of/round-robin, atomic replacement and provider-neutral product endpoints are covered by the passing AI tests. No product workflow selects a named vendor.
- Release position: **P0 CODE GATE PASS**. Before production promotion, run one credentialed staging smoke for a real AI call and one connected social publish; do not start PR7.

### 2026-08-22 — Claude/Codex recovery consolidation

- Integrated Claude commits `2a10ca9` and `3944163` with the provider-neutral P0 recovery commit `0c398e0`; conflicts were resolved against the frozen ownership rules, not by accepting either tree wholesale.
- Preserved the stricter atomic Add Client contract: workspace, OWNER membership, default Brand and usable platform AI routing commit together; unavailable platform AI returns an honest 503 and rolls the client back.
- Preserved publishing state honesty: only selected-workspace durable content opened from Review and already approved can enter the publish flow.
- Replaced provider-specific provisioning-test assumptions with a capability-only test adapter; default provider selection remains catalogue/adapter/capability/policy based.
- Added and verified rich authoritative Brand business fields through onboarding, Brand Master, compiler and Context Gateway; a correction changes the brain version and the next generation brief.
- Final merged evidence: complete Django suite **665 passed, 0 failed** in 657.189 seconds; `makemigrations --check --dry-run` **PASS** with no changes; Django check **PASS** (only the expected local placeholder-secret warning); TypeScript `--noEmit` **PASS**; substantive ESLint on all touched frontend files **PASS with zero warnings** after excluding the repository-wide CRLF/Prettier baseline; production frontend build **PASS**.
- Release position: **MERGED P0 CODE GATE PASS**. PR7 remains closed. Production promotion still requires deployment completion and a live post-deploy smoke.

### 2026-08-22 — Final P0 hardening and OpenAI redundancy

- Added OpenAI as a discovered PR5 provider adapter for text, image, image analysis/captioning and embeddings. Existing workspace routes are unchanged; admins may enable it and place any number of capable providers in an ordered FAILOVER, ROUND_ROBIN or BEST_OF set.
- Kept all product paths provider-neutral. Vendor-specific payloads and errors live only in adapters; user-facing creation copy now names Scaleezy/configured routing rather than Gemini.
- Added explicit Brand Master Save with dirty/saving/saved/failed states, retained failed edits, navigation flush and client-switch addressing safety.
- Closed publishing integrity gaps: raw job PUT/PATCH/DELETE are unavailable, the job publishes the exact approved ContentItem copy, and a request cannot substitute unreviewed text or media.
- Made generated images durable before ContentItem persistence: inline or explicitly temporary provider output is copied to workspace storage, linked through a MarketingAsset and returned as a stable URL.
- Focused adversarial gate: **165 passed, 0 failed** across AI, publishing, generation routing, lifecycle, workspace and layout suites.
- Final backend gate: **690 passed, 0 failed** in 1166.904 seconds. Migration drift check **PASS**; Django check **PASS** apart from the expected local placeholder-secret warning.
- Final frontend gate: TypeScript **PASS**; substantive ESLint across all 21 changed TypeScript files **PASS with zero warnings**; production client/SSR/Nitro build **PASS**.
- Release position: **P0 CODE GATE PASS; PRODUCTION PROMOTION BLOCKED** until Render runs `manage.py run_tasks` and the post-deploy credentialed AI/social smoke succeeds. Knowledge processing, Inspiration analysis and calibration-to-next-generation proof remain explicit P1 work; PR7 remains closed.

### 2026-08-23 — Render worker deployment configuration

- Added one Starter background worker running the existing durable `manage.py run_tasks` command every five seconds. It reuses the web service's Render-managed database, encryption, storage and AI credentials through cross-service references; no secret is duplicated or committed.
- Added a 300-second shutdown allowance so the worker can finish an in-flight provider call or publish after `SIGTERM`, matching the command's graceful-stop contract.
- Verification: YAML parse **PASS**; current official Render Blueprint schema **PASS**; worker command discovery/help **PASS**; focused durable-jobs and publishing suite **35 passed, 0 failed**; diff check **PASS**.
- Release position remains **PRODUCTION PROMOTION BLOCKED** until the Blueprint is synced on Render, the worker reports healthy polling, and the credentialed AI/social smoke succeeds. PR7 remains closed.

### 2026-08-23 — Admin console and open-ended AI completion

- Replaced the implicit provider/routing surface with URL-addressable Overview, Providers, Routing & redundancy, and Activity tabs under the existing OWNER/ADMIN guard. Settings remains free of AI controls.
- Added an explicit catalogue-backed **Add provider** workflow. Workspace admins can add every installed integration, store its encrypted key, optionally override its model and enable it; routing accepts an arbitrary ordered provider set rather than primary-plus-one-failover slots.
- Made adapter discovery recursive and catalogue synchronisation idempotent at deploy time, so adding another adapter expands the Admin catalogue without core router or frontend changes. The operator kill switch remains authoritative.
- Replaced key-presence checks with authenticated, read-only OpenAI/Gemini connection checks; failures are sanitised. New clients may now compose different default providers per required capability in one transaction.
- Focused gate: all **76 AI/Admin backend checks have passing evidence** after supplying the required local test encryption key; targeted frontend lint and TypeScript **PASS**; production client/SSR/Nitro build **PASS**; diff check **PASS**.
- Release position: **ADMIN P0 CODE GATE PASS; DEPLOYMENT NEXT**. P1 and PR7 remain closed until the live Admin tabs and Add provider workflow are confirmed.

### 2026-08-23 — Provider catalogue expansion

- Closed the live Add provider dead end by installing five additional production adapters: Groq, Mistral AI, DeepSeek, OpenRouter and Together AI. The Admin catalogue now has seven integrations including Gemini and OpenAI.
- Kept the PR5 boundary intact: vendor endpoints and payloads exist only in adapters; all product workflows still request capabilities from AIRouter. Each new integration can join an arbitrary ordered Copy route with FAILOVER, ROUND_ROBIN or BEST_OF.
- Preserved security and tenant semantics: workspace keys remain encrypted/write-only, provider destinations are fixed code-owned HTTPS endpoints, and OWNER/ADMIN enforcement is unchanged.
- Verification: focused adapter/catalogue checks **10 passed, 0 failed**; all **75 AI-module tests have passing evidence** after rerunning the three environment-only encryption checks with a valid temporary test key; Python compilation and migration drift checks **PASS**.
- Release position: **P0 PROVIDER CATALOGUE CODE GATE PASS; BACKEND DEPLOYMENT NEXT**. P1 and PR7 remain closed.

### 2026-08-23 — Provider catalogue deploy recovery

- Live evidence showed that the production catalogue still contained only Gemini and OpenAI, so the Add provider dialog correctly had nothing else to offer. The deploy-time sync had not populated the five new adapter rows.
- Added an idempotent, additive data migration for Groq, Mistral AI, DeepSeek, OpenRouter and Together AI. It preserves the operator kill switch and creates no workspace configuration or routes.
- Focused verification: **7 passed, 0 failed**; migration drift check **PASS**.
- Release position: **P0 DEPLOY RECOVERY CODE GATE PASS; BACKEND DEPLOYMENT REQUIRED**. P1 and PR7 remain closed.

### 2026-08-23 — Manual AI onboarding and complete capability routing

- Root cause: the earlier acceptance gate proved arbitrary ordered provider sets but treated catalogue-backed installation as the complete onboarding contract. The first custom endpoint implementation then hard-coded `TEXT`, leaving manual providers eligible only for Copy despite the PR5 capability-routing requirement.
- Removed every onboarding default. Admin must explicitly enter provider name, exact model, public HTTPS endpoint, optional key/token, protocol and the capabilities the endpoint actually serves.
- OpenAI-compatible custom endpoints support their standard text, image, vision/caption and embedding paths. The provider-neutral Scaleezy universal JSON contract supports all seven routing capabilities, including video generation and analysis.
- Capability declaration and routing remain separate: each declared provider becomes eligible, while Admin explicitly composes each ordered FAILOVER, ROUND_ROBIN or BEST_OF route. No provider or route is chosen silently.
- Tenant isolation, encrypted credentials, public-endpoint SSRF controls and the frozen AIRouter ownership boundary remain enforced. P1 and PR7 remain closed until this P0 is deployed.
