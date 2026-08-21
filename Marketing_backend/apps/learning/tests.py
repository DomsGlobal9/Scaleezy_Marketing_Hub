"""
Tests for PR3 — Learning Fabric Foundation.

Happy paths prove the fabric is connected; the rest prove it cannot be talked
into treating one opinion as brand law, or into leaking across a tenant
boundary. Negative assertions run through `apps.common.testing`, so every
rejection also proves the database did not move.
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.test import TestCase
from rest_framework import status

from apps.brands.models import Brand
from apps.common.testing import (
    TenantFixtureMixin,
    TenantSecurityAssertions,
    workspace_header,
)
from apps.workspaces.models import WorkspaceMember

from .models import BrandPreference, BrandRule, LearningEvent, LearningScope, SubjectType
from .services import (
    LearningError,
    create_explicit_rule,
    deactivate_rule,
    promote_preference_to_rule,
    record_event,
    reinforce_preference,
    resolve_preferences,
    resolve_rules,
)

User = get_user_model()

EVENTS_URL = '/api/marketing/learning-events/'
PREFERENCES_URL = '/api/marketing/brand-preferences/'
RULES_URL = '/api/marketing/brand-rules/'


class LearningTestBase(TenantFixtureMixin, TenantSecurityAssertions, TestCase):
    def setUp(self):
        self.workspace1 = self.make_workspace('Workspace 1', 'c1')
        self.user1, self.client1 = self.authenticate_as(
            self.workspace1, WorkspaceMember.Role.ADMIN, 'user1'
        )
        self.viewer, self.viewer_client = self.authenticate_as(
            self.workspace1, WorkspaceMember.Role.VIEWER, 'viewer'
        )
        self.brand1 = Brand.objects.create(workspace=self.workspace1, name='Brand 1')
        self.brand1b = Brand.objects.create(workspace=self.workspace1, name='Brand 1b')

        self.workspace2 = self.make_workspace('Workspace 2', 'c2')
        self.user2, self.client2 = self.authenticate_as(
            self.workspace2, WorkspaceMember.Role.ADMIN, 'user2'
        )
        self.brand2 = Brand.objects.create(workspace=self.workspace2, name='Brand 2')

    def ws1(self):
        return workspace_header(self.workspace1)

    def ws2(self):
        return workspace_header(self.workspace2)

    def event_payload(self, **overrides):
        payload = {
            'brand': str(self.brand1.id),
            'event_type': LearningEvent.EventType.APPROVED,
            'outcome': LearningEvent.Outcome.POSITIVE,
            'subject_type': SubjectType.CONTENT_ITEM,
        }
        payload.update(overrides)
        return payload

    def rule_payload(self, **overrides):
        payload = {
            'brand': str(self.brand1.id),
            'text': 'Never use stock photography of handshakes.',
            'hardness': BrandRule.Hardness.HARD,
        }
        payload.update(overrides)
        return payload

    def make_event(self, brand=None, **kwargs):
        return record_event(
            workspace=kwargs.pop('workspace', self.workspace1),
            brand=self.brand1 if brand is None else brand,
            event_type=kwargs.pop('event_type', LearningEvent.EventType.REJECTED),
            outcome=kwargs.pop('outcome', LearningEvent.Outcome.NEGATIVE),
            **kwargs,
        )

    def make_established_preference(self):
        for _ in range(BrandPreference.ESTABLISHED_AT_EVIDENCE):
            preference = reinforce_preference(
                workspace=self.workspace1,
                brand=self.brand1,
                category='TYPOGRAPHY',
                attribute='headline_face',
                value='Condensed grotesque',
            )
        return preference


class LearningEventTests(LearningTestBase):
    def test_record_and_read_an_event(self):
        response = self.client1.post(
            EVENTS_URL, self.event_payload(), format='json', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        body = response.json()
        self.assertEqual(body['workspace'], str(self.workspace1.id))
        self.assertEqual(body['created_by'], self.user1.id)
        # Consent to pool evidence is never assumed.
        self.assertFalse(body['eligibility_for_aggregate_learning'])

    def test_positive_outcomes_are_captured_not_only_complaints(self):
        for event_type, outcome in (
            (LearningEvent.EventType.APPROVED, LearningEvent.Outcome.POSITIVE),
            (LearningEvent.EventType.PUBLISHED, LearningEvent.Outcome.POSITIVE),
            (LearningEvent.EventType.REJECTED, LearningEvent.Outcome.NEGATIVE),
        ):
            with self.subTest(event_type=event_type):
                event = self.make_event(event_type=event_type, outcome=outcome)
                self.assertEqual(event.outcome, outcome)
        self.assertEqual(
            LearningEvent.objects.filter(
                outcome=LearningEvent.Outcome.POSITIVE
            ).count(),
            2,
        )

    def test_events_are_idempotent_on_a_dedupe_key(self):
        first = self.make_event(dedupe_key='feedback:abc')
        second = self.make_event(dedupe_key='feedback:abc')
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(LearningEvent.objects.count(), 1)

    def test_duplicate_dedupe_keys_are_refused_by_the_database(self):
        self.make_event(dedupe_key='feedback:abc')
        with self.assertRaises(IntegrityError):
            LearningEvent.objects.create(
                workspace=self.workspace1,
                brand=self.brand1,
                event_type=LearningEvent.EventType.REJECTED,
                dedupe_key='feedback:abc',
            )

    def test_the_same_dedupe_key_is_free_in_another_workspace(self):
        self.make_event(dedupe_key='feedback:abc')
        other = record_event(
            workspace=self.workspace2,
            brand=self.brand2,
            event_type=LearningEvent.EventType.REJECTED,
            dedupe_key='feedback:abc',
        )
        self.assertEqual(LearningEvent.objects.count(), 2)
        self.assertEqual(other.workspace_id, self.workspace2.id)

    def test_events_cannot_be_edited_or_deleted(self):
        event = self.make_event()
        url = f'{EVENTS_URL}{event.id}/'
        for method in ('patch', 'put', 'delete'):
            with self.subTest(method=method):
                response = getattr(self.client1, method)(url, {}, format='json', **self.ws1())
                self.assertEqual(
                    response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED
                )
        self.assertTrue(LearningEvent.objects.filter(pk=event.pk).exists())

    def test_aggregate_eligibility_filter_is_explicit(self):
        self.make_event(dedupe_key='a')
        eligible = record_event(
            workspace=self.workspace1,
            brand=self.brand1,
            event_type=LearningEvent.EventType.PUBLISHED,
            eligible_for_aggregate=True,
            dedupe_key='b',
        )
        rows = self.client1.get(f'{EVENTS_URL}?aggregate_eligible=true', **self.ws1()).json()
        self.assertEqual([row['id'] for row in rows], [str(eligible.id)])


class PreferenceThresholdTests(LearningTestBase):
    def test_one_event_is_an_opinion_not_an_established_preference(self):
        preference = reinforce_preference(
            workspace=self.workspace1,
            brand=self.brand1,
            category='TYPOGRAPHY',
            attribute='headline_face',
            value='Condensed grotesque',
        )
        self.assertEqual(preference.evidence_count, 1)
        self.assertEqual(preference.state, BrandPreference.State.EMERGING)

    def test_the_second_event_establishes_it(self):
        preference = self.make_established_preference()
        self.assertEqual(preference.evidence_count, 2)
        self.assertEqual(preference.state, BrandPreference.State.ESTABLISHED)

    def test_a_preference_cannot_be_declared_through_the_api(self):
        """There is no endpoint to assert a brand truth with nothing behind it."""
        response = self.client1.post(
            PREFERENCES_URL,
            {
                'brand': str(self.brand1.id),
                'category': 'TYPOGRAPHY',
                'attribute': 'headline_face',
                'state': BrandPreference.State.ESTABLISHED,
            },
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertFalse(BrandPreference.objects.exists())

    def test_only_one_live_preference_per_attribute(self):
        self.make_established_preference()
        with self.assertRaises(IntegrityError):
            BrandPreference.objects.create(
                workspace=self.workspace1,
                brand=self.brand1,
                category='TYPOGRAPHY',
                attribute='headline_face',
                value='Serif display',
            )

    def test_retiring_a_preference_takes_it_out_of_resolution(self):
        preference = self.make_established_preference()
        response = self.client1.post(
            f'{PREFERENCES_URL}{preference.id}/retire/', format='json', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        preference.refresh_from_db()
        self.assertEqual(preference.state, BrandPreference.State.RETIRED)
        self.assertNotIn(
            preference,
            resolve_preferences(workspace=self.workspace1, brand=self.brand1),
        )

    def test_new_evidence_does_not_revive_a_retired_preference(self):
        preference = self.make_established_preference()
        preference.state = BrandPreference.State.RETIRED
        preference.save(update_fields=['state'])
        with self.assertRaises(LearningError):
            reinforce_preference(
                workspace=self.workspace1,
                brand=self.brand1,
                category='TYPOGRAPHY',
                attribute='headline_face',
            )


class RuleAuthorityTests(LearningTestBase):
    def test_one_off_feedback_cannot_become_a_rule(self):
        """The PR3 acceptance criterion."""
        preference = reinforce_preference(
            workspace=self.workspace1,
            brand=self.brand1,
            category='TYPOGRAPHY',
            attribute='headline_face',
            value='Condensed grotesque',
        )
        single_event = self.make_event()
        with self.assertRaises(LearningError):
            promote_preference_to_rule(
                preference=preference, evidence_events=[single_event]
            )
        self.assertFalse(BrandRule.objects.exists())

    def test_corroborated_evidence_produces_a_soft_learned_rule(self):
        preference = self.make_established_preference()
        events = [self.make_event(dedupe_key=f'e{i}') for i in range(2)]
        rule = promote_preference_to_rule(preference=preference, evidence_events=events)
        self.assertEqual(rule.origin, BrandRule.Origin.LEARNED)
        self.assertEqual(rule.hardness, BrandRule.Hardness.SOFT)
        self.assertEqual(
            set(rule.evidence_event_ids), {str(e.pk) for e in events}
        )

    def test_an_emerging_preference_cannot_back_a_rule(self):
        preference = reinforce_preference(
            workspace=self.workspace1, brand=self.brand1,
            category='TYPOGRAPHY', attribute='headline_face',
        )
        events = [self.make_event(dedupe_key=f'e{i}') for i in range(2)]
        with self.assertRaises(LearningError):
            promote_preference_to_rule(preference=preference, evidence_events=events)

    def test_a_learned_rule_can_never_be_hard(self):
        """Enforced in the schema, not only in the service."""
        with self.assertRaises(IntegrityError):
            BrandRule.objects.create(
                workspace=self.workspace1,
                brand=self.brand1,
                text='Inferred constraint',
                origin=BrandRule.Origin.LEARNED,
                hardness=BrandRule.Hardness.HARD,
            )

    def test_an_explicit_instruction_may_be_hard_and_carries_provenance(self):
        response = self.client1.post(
            RULES_URL, self.rule_payload(), format='json', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        rule = BrandRule.objects.get(id=response.json()['data']['id'])
        self.assertEqual(rule.hardness, BrandRule.Hardness.HARD)
        self.assertEqual(rule.origin, BrandRule.Origin.EXPLICIT)
        self.assertEqual(rule.created_by_id, self.user1.id)

    def test_the_api_cannot_mint_a_learned_rule(self):
        response = self.client1.post(
            RULES_URL,
            self.rule_payload(
                origin=BrandRule.Origin.LEARNED,
                hardness=BrandRule.Hardness.SOFT,
                evidence_event_ids=['forged'],
                confidence=1.0,
            ),
            format='json',
            **self.ws1(),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        rule = BrandRule.objects.get(id=response.json()['data']['id'])
        self.assertEqual(rule.origin, BrandRule.Origin.EXPLICIT)
        self.assertEqual(rule.evidence_event_ids, [])

    def test_rules_are_deactivated_not_deleted(self):
        rule = create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1, text='No handshakes',
            created_by=self.user1,
        )
        delete = self.client1.delete(f'{RULES_URL}{rule.id}/', **self.ws1())
        self.assertEqual(delete.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

        response = self.client1.post(
            f'{RULES_URL}{rule.id}/deactivate/', format='json', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)
        self.assertEqual(rule.deactivated_by_id, self.user1.id)
        self.assertIsNotNone(rule.deactivated_at)
        self.assertTrue(BrandRule.objects.filter(pk=rule.pk).exists())

    def test_a_rule_cannot_be_edited_back_into_force(self):
        """Rules have no update route at all: reactivating one, or relabelling
        an explicit rule as learned, would rewrite the provenance a generation
        already cited."""
        rule = create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1, text='No handshakes',
        )
        deactivate_rule(rule=rule)
        for method in ('patch', 'put'):
            with self.subTest(method=method):
                response = getattr(self.client1, method)(
                    f'{RULES_URL}{rule.id}/',
                    {'is_active': True, 'origin': BrandRule.Origin.LEARNED},
                    format='json',
                    **self.ws1(),
                )
                self.assertEqual(
                    response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED
                )
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)
        self.assertEqual(rule.origin, BrandRule.Origin.EXPLICIT)

    def test_resolution_orders_hard_rules_first(self):
        create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1, text='Soft one',
            hardness=BrandRule.Hardness.SOFT, priority=9,
        )
        hard = create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1, text='Hard one',
            hardness=BrandRule.Hardness.HARD, priority=1,
        )
        resolved = list(resolve_rules(workspace=self.workspace1, brand=self.brand1))
        self.assertEqual(resolved[0].id, hard.id)

    def test_resolution_excludes_deactivated_rules(self):
        rule = create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1, text='No handshakes',
        )
        deactivate_rule(rule=rule)
        self.assertNotIn(
            rule, resolve_rules(workspace=self.workspace1, brand=self.brand1)
        )

    def test_resolution_keeps_another_brand_out(self):
        mine = create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1, text='Mine',
        )
        theirs = create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1b, text='Theirs',
        )
        resolved = list(resolve_rules(workspace=self.workspace1, brand=self.brand1))
        self.assertIn(mine, resolved)
        self.assertNotIn(theirs, resolved)

    def test_workspace_wide_rules_apply_to_every_brand(self):
        tenant_rule = create_explicit_rule(
            workspace=self.workspace1, brand=None, text='Tenant-wide',
            scope=LearningScope.TENANT,
        )
        for brand in (self.brand1, self.brand1b):
            with self.subTest(brand=brand.name):
                self.assertIn(
                    tenant_rule,
                    resolve_rules(workspace=self.workspace1, brand=brand),
                )


class LearningTenantIsolationTests(LearningTestBase):
    def test_cross_tenant_brand_injection_blocked_on_events(self):
        self.assert_cross_tenant_fk_rejected(
            client=self.client1, url=EVENTS_URL, workspace=self.workspace1,
            model=LearningEvent, payload=self.event_payload(),
            field='brand', foreign_id=self.brand2.id,
        )

    def test_cross_tenant_brand_injection_blocked_on_rules(self):
        self.assert_cross_tenant_fk_rejected(
            client=self.client1, url=RULES_URL, workspace=self.workspace1,
            model=BrandRule, payload=self.rule_payload(),
            field='brand', foreign_id=self.brand2.id,
        )

    def test_service_refuses_a_cross_tenant_brand(self):
        with self.assertRaises(LearningError):
            record_event(
                workspace=self.workspace1,
                brand=self.brand2,
                event_type=LearningEvent.EventType.APPROVED,
            )
        self.assertFalse(LearningEvent.objects.exists())

    def test_model_refuses_a_cross_tenant_brand(self):
        """The invariant holds for ORM writers, not only for requests."""
        for model in (LearningEvent, BrandRule):
            with self.subTest(model=model.__name__):
                with self.assertRaises(ValidationError):
                    model.objects.create(
                        workspace=self.workspace1,
                        brand=self.brand2,
                        **(
                            {'event_type': LearningEvent.EventType.APPROVED}
                            if model is LearningEvent
                            else {'text': 'smuggled'}
                        ),
                    )

    def test_promotion_refuses_evidence_from_another_brand(self):
        preference = self.make_established_preference()
        foreign = [
            self.make_event(brand=self.brand1b, dedupe_key=f'x{i}') for i in range(2)
        ]
        with self.assertRaises(LearningError):
            promote_preference_to_rule(preference=preference, evidence_events=foreign)
        self.assertFalse(BrandRule.objects.exists())

    def test_records_are_hidden_from_the_other_tenant(self):
        event = self.make_event()
        rule = create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1, text='Mine',
        )
        preference = self.make_established_preference()
        for url, obj in (
            (EVENTS_URL, event), (RULES_URL, rule), (PREFERENCES_URL, preference),
        ):
            with self.subTest(url=url):
                self.assert_object_hidden_from_other_workspace(
                    client=self.client2,
                    detail_url=f'{url}{obj.id}/',
                    list_url=url,
                    workspace=self.workspace2,
                    object_id=obj.id,
                )

    def test_every_mutation_path_is_404_for_another_tenant(self):
        rule = create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1, text='Mine',
        )
        preference = self.make_established_preference()
        attempts = [
            self.client2.post(
                f'{RULES_URL}{rule.id}/deactivate/', format='json', **self.ws2()
            ),
            self.client2.post(
                f'{PREFERENCES_URL}{preference.id}/retire/', format='json', **self.ws2()
            ),
        ]
        for response in attempts:
            self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        rule.refresh_from_db()
        preference.refresh_from_db()
        self.assertTrue(rule.is_active)
        self.assertEqual(preference.state, BrandPreference.State.ESTABLISHED)

    def test_staff_without_membership_cannot_read(self):
        staff = User.objects.create_user(username='staff', password='p', is_staff=True)
        from rest_framework.test import APIClient

        staff_client = APIClient()
        staff_client.force_authenticate(user=staff)
        event = self.make_event()
        response = staff_client.get(f'{EVENTS_URL}{event.id}/', **self.ws1())
        self.assertIn(
            response.status_code,
            (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND),
        )


class LearningRBACTests(LearningTestBase):
    def test_viewer_can_read(self):
        self.make_event()
        response = self.viewer_client.get(EVENTS_URL, **self.ws1())
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_viewer_cannot_record_an_event(self):
        self.assert_viewer_mutation_denied(
            client=self.viewer_client, method='post', url=EVENTS_URL,
            workspace=self.workspace1, model=LearningEvent,
            payload=self.event_payload(),
        )

    def test_viewer_cannot_state_a_rule(self):
        self.assert_viewer_mutation_denied(
            client=self.viewer_client, method='post', url=RULES_URL,
            workspace=self.workspace1, model=BrandRule,
            payload=self.rule_payload(),
        )

    def test_viewer_cannot_deactivate_or_retire(self):
        rule = create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1, text='Mine',
        )
        preference = self.make_established_preference()
        for url, model in (
            (f'{RULES_URL}{rule.id}/deactivate/', BrandRule),
            (f'{PREFERENCES_URL}{preference.id}/retire/', BrandPreference),
        ):
            with self.subTest(url=url):
                self.assert_viewer_mutation_denied(
                    client=self.viewer_client, method='post', url=url,
                    workspace=self.workspace1, model=model, payload={},
                )
        rule.refresh_from_db()
        preference.refresh_from_db()
        self.assertTrue(rule.is_active)
        self.assertEqual(preference.state, BrandPreference.State.ESTABLISHED)


class FeedbackBridgeTests(LearningTestBase):
    """PR3 adapter: existing corrective feedback flows into the fabric.

    The bridge is additive — `apps.feedback` still writes its own row and runs
    its own training pass, and both are asserted here so the migration cannot
    quietly break the read side that already exists.
    """

    def make_content_item(self, workspace=None, brand=None):
        from apps.content.models import ContentItem

        return ContentItem.objects.create(
            workspace=workspace or self.workspace1,
            brand=self.brand1 if brand is None else brand,
            headline='Festive drop',
            status=ContentItem.Status.PENDING_REVIEW,
        )

    def test_capture_mirrors_a_verdict_into_the_fabric(self):
        from apps.feedback.models import Feedback
        from apps.feedback.services import capture

        item = self.make_content_item()
        feedback = capture(
            content_item=item,
            user=self.user1,
            verdict=Feedback.Verdict.REJECT,
            feedback_text='Headline is unreadable',
        )

        # The old behaviour is untouched.
        self.assertIsNotNone(feedback)
        self.assertTrue(Feedback.objects.filter(pk=feedback.pk).exists())

        event = LearningEvent.objects.get(source_id=feedback.pk)
        self.assertEqual(event.event_type, LearningEvent.EventType.REJECTED)
        self.assertEqual(event.outcome, LearningEvent.Outcome.NEGATIVE)
        self.assertEqual(event.workspace_id, self.workspace1.id)
        self.assertEqual(event.brand_id, self.brand1.id)
        self.assertEqual(event.subject_id, item.pk)
        self.assertEqual(event.source_type, SubjectType.FEEDBACK)
        self.assertEqual(event.context['verdict'], Feedback.Verdict.REJECT)

    def test_approvals_reach_the_fabric_too(self):
        """The old engine learned only from complaints."""
        from apps.feedback.models import Feedback
        from apps.feedback.services import capture

        feedback = capture(
            content_item=self.make_content_item(),
            user=self.user1,
            verdict=Feedback.Verdict.APPROVE,
            feedback_text='Exactly right',
        )
        event = LearningEvent.objects.get(source_id=feedback.pk)
        self.assertEqual(event.event_type, LearningEvent.EventType.APPROVED)
        self.assertEqual(event.outcome, LearningEvent.Outcome.POSITIVE)

    def test_replaying_the_bridge_does_not_double_count(self):
        from apps.feedback.models import Feedback
        from apps.feedback.services import capture

        from .adapters import record_feedback_event

        feedback = capture(
            content_item=self.make_content_item(),
            user=self.user1,
            verdict=Feedback.Verdict.NEEDS_EDITS,
        )
        first = LearningEvent.objects.get(source_id=feedback.pk)
        again = record_feedback_event(feedback)
        self.assertEqual(again.pk, first.pk)
        self.assertEqual(LearningEvent.objects.filter(source_id=feedback.pk).count(), 1)

    def test_a_failing_bridge_never_costs_a_reviewer_their_verdict(self):
        from unittest.mock import patch

        from apps.feedback.models import Feedback
        from apps.feedback.services import capture

        with patch(
            'apps.learning.adapters.record_feedback_event',
            side_effect=RuntimeError('fabric down'),
        ):
            feedback = capture(
                content_item=self.make_content_item(),
                user=self.user1,
                verdict=Feedback.Verdict.REJECT,
            )

        self.assertIsNotNone(feedback)
        self.assertTrue(Feedback.objects.filter(pk=feedback.pk).exists())
        self.assertFalse(LearningEvent.objects.exists())

    def test_the_bridge_stays_inside_the_tenant(self):
        from apps.feedback.models import Feedback
        from apps.feedback.services import capture

        item = self.make_content_item(workspace=self.workspace2, brand=self.brand2)
        feedback = capture(
            content_item=item, user=self.user2, verdict=Feedback.Verdict.REJECT
        )
        event = LearningEvent.objects.get(source_id=feedback.pk)
        self.assertEqual(event.workspace_id, self.workspace2.id)
        self.assertEqual(
            LearningEvent.objects.filter(workspace=self.workspace1).count(), 0
        )
