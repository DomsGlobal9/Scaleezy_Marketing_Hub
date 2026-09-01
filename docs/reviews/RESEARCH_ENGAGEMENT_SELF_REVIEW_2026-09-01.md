# Research & Engagement Closure — Immutable Self Review

## Reviewed delta

- Base: `dddd3d80`
- Branch: `feat/research-engagement`
- Contract: `docs/reviews/RESEARCH_ENGAGEMENT_PREFLIGHT_2026-09-01.md`
- Scope: live-web creative discovery, verified inspiration adoption, governed
  social engagement, provider-neutral AI drafting, and honest operator health.

## Requirement evidence

| ID | Verdict | Evidence |
|---|---|---|
| RE-001 | PASS | `ResearchClosureTests.test_create_is_queued_and_cross_tenant_brand_is_refused` proves research is asynchronous and tenant scoped. |
| RE-002 | PASS | `OpenAIAdapterTests.test_research_requires_and_records_a_real_web_search_call` proves the installed OpenAI research path invokes the Responses API `web_search` tool. `test_research_refuses_model_memory_without_web_search` proves remembered/hallucinated links are not accepted as live research. |
| RE-003 | PASS | `ResearchClosureTests.test_task_routes_research_verifies_citations_and_is_idempotent` proves every candidate is bounded, deduplicated, and verified through the existing redirect-safe public fetcher before adoption. |
| RE-004 | PASS | `test_unverified_or_restricted_findings_cannot_be_adopted` and `test_adoption_is_idempotent_and_preserves_lineage` prove rights default to UNKNOWN, unsafe/restricted candidates are blocked, and accepted discoveries enter the existing `BrandInspiration` owner with source lineage. |
| RE-005 | PASS | `EngagementClosureTests.test_platform_sync_is_bounded_normalized_and_idempotent` proves connected-account ingestion is bounded and deduplicated. X and YouTube HTTP normalization is proven by `XEngagementAdapterTests` and the new YouTube fetch/reply tests. |
| RE-006 | PASS | `test_ai_draft_uses_dedicated_route_and_never_sends` proves reply drafting uses `AIRouter(ENGAGEMENT_RESPONSE)` and cannot send automatically. OpenAI, Gemini, installed OpenAI-compatible providers, and the universal JSON contract support the capability without vendor logic in product services. |
| RE-007 | PASS | `test_approval_is_human_evidence_but_does_not_send`, `test_send_is_single_claim_and_marks_resolved_only_after_platform_success`, and `test_failed_platform_reply_stays_approved_and_never_claims_sent` prove explicit approval and honest send state. |
| RE-008 | PASS | `test_collision_lock_blocks_a_second_operator` and `test_sending_or_closed_item_cannot_be_claimed_or_reapproved` prove collaboration and send-state races cannot reopen in-flight work. |
| RE-009 | PASS | `ProcessingHealthTests` proves research failures, inbox-sync failures, draft failures, and stale sends are live numeric operator signals rather than disconnected zeroes. |
| RE-010 | PASS | The Growth Engine UI exposes the complete Research → Direct → Create → Review → Publish → Engage → Learn loop, unrestricted search terms/sources, rights controls, verified adoption, inbox sync, assignment, draft review, approval, sending, and failure states. |

## Adversarial review

| Attack path | Verdict | Evidence |
|---|---|---|
| Cross-tenant brand, connection, finding, item, assignee or saved reply | PASS | Serializer relation querysets, model graph validation, workspace-scoped viewsets, and `test_other_tenant_cannot_read_finding` / `test_other_tenant_cannot_see_or_act_on_an_item`. |
| LLM invents a current source | PASS | Generic chat-completion adapters do not advertise RESEARCH; OpenAI requires an actual `web_search_call`; every returned source must still pass the pinned public fetcher. |
| Research provider returns a private or redirecting target | PASS | `safe_fetch` revalidates and pins every target; unsafe/unreachable findings are persisted as failed verification and cannot be adopted. |
| Copyright status is inferred from public visibility | PASS | Rights always start UNKNOWN and only an explicit user action changes them; public reference does not become an owned asset. |
| Duplicate platform events or repeated adoption | PASS | Database uniqueness and idempotent service paths are covered by the sync and adoption tests. |
| Two operators send the same reply | PASS | One conditional APPROVED → SENDING claim occurs before the platform request; only one request can own it. |
| Provider/platform failure reported as success | PASS | Failed research/sync/draft/send states remain durable and visible; send success is recorded only after the external API returns an id. |
| Unsupported network silently faked | PASS | Only X mentions/replies and YouTube comments/replies are enabled; unsupported platforms return an explicit unavailable error. |

## Gates

- PASS — focused backend verification: **71 tests, 0 failures, 0 errors**;
  final engagement/platform hardening subset: **26 tests, 0 failures, 0 errors**.
- PASS — full backend regression: **1023 tests, 0 failures, 0 errors**.
- PASS — frontend Prettier check for the Growth Engine and route files.
- PASS — frontend TypeScript: `tsc --noEmit`.
- PASS — targeted frontend ESLint for the Growth Engine route.
- PASS — frontend production build (client, SSR and Nitro/Cloudflare output).
- PASS — `manage.py makemigrations --check --dry-run`: no changes detected.
- PASS — `manage.py check`: no errors; only the expected local placeholder
  `SECRET_KEY` warning under the explicit SQLite fallback.
- PASS — `git diff --check`.

## Boundary confirmation

- PASS — PR0–PR7 tenancy, Brand Brain, Learning Fabric, Context Gateway and
  AI Router ownership are preserved.
- PASS — no provider or model is forced on a client; RESEARCH and
  ENGAGEMENT_RESPONSE are independent admin-routable capabilities with normal
  failover/best-of/round-robin strategy support.
- PASS — no automatic public replies and no fake rights grant.
- PASS — publishing state or billing semantics were not changed.
- N/A — Instagram/Facebook/LinkedIn/TikTok inbox reads and replies require
  their platform-specific approved API permissions and remain honestly
  unavailable rather than simulated.

## Final verdict

**READY** — zero FAIL and zero NOT VERIFIED within the frozen Research &
Engagement Closure scope.
