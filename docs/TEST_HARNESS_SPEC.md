# TEST_HARNESS_SPEC.md — Reusable Security Accelerator

## Goal
Reduce repeated boilerplate across PR2–PR10 while increasing adversarial coverage.

Create reusable test helpers ONLY if they fit existing test conventions and do not create an unnecessary abstraction.

Useful helper concepts:
- authenticate_as(workspace, role)
- assert_cross_tenant_fk_rejected(endpoint, payload_field, foreign_id)
- assert_cross_brand_fk_rejected(...)
- assert_viewer_mutation_denied(method, endpoint, payload)
- assert_field_immutable(endpoint, field, new_value)
- assert_protected_state_not_patchable(...)
- assert_object_hidden_from_other_workspace(...)
- assert_duplicate_action_idempotent(...) when applicable

## Requirements
- Helpers must assert BOTH response and database non-mutation.
- Keep failure messages descriptive.
- Prefer parameterization/table-driven cases where supported by current framework.
- Never hide endpoint-specific semantics behind overly generic helpers.
- A helper is valuable only if reused by multiple modules/paths.

## PR2 minimum direct evidence
Named tests should clearly cover:
- cross-tenant inspiration brand
- cross-tenant inspiration source
- cross-brand source
- immutable brand
- viewer write denial
- cross-tenant signal inspiration
- origin escalation prevention
- archived/revoked eligibility
