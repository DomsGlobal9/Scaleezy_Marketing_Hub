"""
Tests for PR3 — Learning Fabric Foundation.

Happy paths prove the fabric is connected; the rest prove it cannot be talked
into treating one opinion as brand law, or into leaking across a tenant
boundary. Negative assertions run through `apps.common.testing`, so every
rejection also proves the database did not move.
"""
from datetime import datetime, timedelta, timezone as dt_timezone

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

from .models import (
    BrandPreference,
    BrandRule,
    LearningEvent,
    LearningScope,
    PreferenceEvidence,
    SubjectType,
)
from .services import (
    LearningError,
    create_explicit_rule,
    deactivate_rule,
    promote_preference_to_rule,
    preference_evidence_events,
    record_event,
    reinforce_preference,
    resolve_preferences,
    resolve_rules,
)

User = get_user_model()

# A stamp of our own, for the places where an assertion would otherwise rest
# on how finely the host clock ticks.
FIXED_TIME = datetime(2026, 1, 1, 9, 0, tzinfo=dt_timezone.utc)

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

    def reinforce(self, event, **kwargs):
        return reinforce_preference(
            workspace=kwargs.pop('workspace', self.workspace1),
            brand=kwargs.pop('brand', self.brand1),
            category=kwargs.pop('category', 'TYPOGRAPHY'),
            attribute=kwargs.pop('attribute', 'headline_face'),
            value=kwargs.pop('value', 'Condensed grotesque'),
            event=event,
            **kwargs,
        )

    def make_established_preference(self):
        for index in range(BrandPreference.ESTABLISHED_AT_EVIDENCE):
            preference = self.reinforce(self.make_event(dedupe_key=f'ev{index}'))
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
        preference = self.reinforce(self.make_event())
        self.assertEqual(preference.evidence_count, 1)
        self.assertEqual(preference.state, BrandPreference.State.EMERGING)

    def test_replaying_the_same_event_counts_once(self):
        """The CTO blocker: a retried job must not make one occurrence look
        like two."""
        event = self.make_event(dedupe_key='replay-me')
        first = self.reinforce(event)
        self.assertEqual(first.evidence_count, 1)

        for _ in range(3):
            again = self.reinforce(event)

        self.assertEqual(again.pk, first.pk)
        self.assertEqual(again.evidence_count, 1)
        self.assertEqual(
            again.state, BrandPreference.State.EMERGING,
            "a replayed event carried the preference over the threshold",
        )
        self.assertEqual(PreferenceEvidence.objects.filter(preference=again).count(), 1)

    def test_two_distinct_events_count_twice(self):
        self.reinforce(self.make_event(dedupe_key='a'))
        preference = self.reinforce(self.make_event(dedupe_key='b'))
        self.assertEqual(preference.evidence_count, 2)
        self.assertEqual(
            PreferenceEvidence.objects.filter(preference=preference).count(), 2
        )

    def test_evidence_lineage_is_inspectable(self):
        events = [self.make_event(dedupe_key=f'l{i}') for i in range(2)]
        for event in events:
            preference = self.reinforce(event)

        # Both lineage paths order by created_at alone, so two rows created in
        # one clock tick tie and SQLite falls back to the pk index - random
        # UUID order. Space them by hand so the assertion is about lineage.
        for offset, event in enumerate(events):
            stamp = FIXED_TIME + timedelta(minutes=offset)
            LearningEvent.objects.filter(pk=event.pk).update(created_at=stamp)
            PreferenceEvidence.objects.filter(
                preference=preference, learning_event=event
            ).update(created_at=stamp)

        self.assertEqual(
            [e.pk for e in preference_evidence_events(preference)],
            [e.pk for e in events],
        )
        body = self.client1.get(
            f'{PREFERENCES_URL}{preference.id}/', **self.ws1()
        ).json()
        self.assertEqual(body['evidence_count'], 2)
        self.assertEqual(body['evidence_event_ids'], [str(e.pk) for e in events])

    def test_evidence_must_come_from_the_same_workspace(self):
        foreign = record_event(
            workspace=self.workspace2, brand=self.brand2,
            event_type=LearningEvent.EventType.REJECTED,
        )
        with self.assertRaises(LearningError):
            self.reinforce(foreign)
        self.assertFalse(BrandPreference.objects.exists())

    def test_evidence_must_come_from_the_same_brand(self):
        other_brand_event = self.make_event(brand=self.brand1b, dedupe_key='ob')
        with self.assertRaises(LearningError):
            self.reinforce(other_brand_event)
        self.assertFalse(PreferenceEvidence.objects.exists())

    def test_model_refuses_cross_tenant_evidence(self):
        """The invariant holds for ORM writers, not only through the service."""
        preference = self.reinforce(self.make_event(dedupe_key='p'))
        foreign = record_event(
            workspace=self.workspace2, brand=self.brand2,
            event_type=LearningEvent.EventType.REJECTED,
        )
        with self.assertRaises(ValidationError):
            PreferenceEvidence.objects.create(
                preference=preference, learning_event=foreign
            )

    def test_duplicate_evidence_pairs_are_refused_by_the_database(self):
        preference = self.reinforce(self.make_event(dedupe_key='d'))
        existing = PreferenceEvidence.objects.get(preference=preference)
        with self.assertRaises(IntegrityError):
            PreferenceEvidence.objects.create(
                preference=preference, learning_event=existing.learning_event
            )

    def test_it_becomes_established_only_after_two_distinct_events(self):
        preference = self.reinforce(self.make_event(dedupe_key='one'))
        self.assertEqual(preference.state, BrandPreference.State.EMERGING)

        preference = self.reinforce(self.make_event(dedupe_key='one'))
        self.assertEqual(
            preference.state, BrandPreference.State.EMERGING,
            "the same event was counted twice",
        )

        preference = self.reinforce(self.make_event(dedupe_key='two'))
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
        """Retiring withdraws THAT record; it does not retire the subject.

        This used to raise, which read as "do not revive" but actually meant
        the attribute could never accumulate evidence again: every later
        judgment about it hit the retired row and was swallowed, invisibly and
        permanently. The rule the code always documented — "new evidence
        starts a new record" — is what it now does.
        """
        preference = self.make_established_preference()
        preference.state = BrandPreference.State.RETIRED
        preference.save(update_fields=['state'])

        successor = self.reinforce(self.make_event(dedupe_key='after-retire'))

        self.assertNotEqual(successor.pk, preference.pk)
        self.assertNotEqual(successor.state, BrandPreference.State.RETIRED)
        preference.refresh_from_db()
        self.assertEqual(
            preference.state, BrandPreference.State.RETIRED,
            'the retired record stays retired; it is not revived',
        )


class RuleAuthorityTests(LearningTestBase):
    def test_one_off_feedback_cannot_become_a_rule(self):
        """The PR3 acceptance criterion."""
        single_event = self.make_event()
        preference = self.reinforce(single_event)
        with self.assertRaises(LearningError):
            promote_preference_to_rule(preference=preference)
        self.assertFalse(BrandRule.objects.exists())

    def test_corroborated_evidence_produces_a_soft_learned_rule(self):
        preference = self.make_established_preference()
        rule = promote_preference_to_rule(preference=preference)
        self.assertEqual(rule.origin, BrandRule.Origin.LEARNED)
        self.assertEqual(rule.hardness, BrandRule.Hardness.SOFT)
        # The cited lineage IS the preference's evidence, not a list the
        # caller handed in.
        self.assertEqual(
            set(rule.evidence_event_ids),
            {str(e.pk) for e in preference_evidence_events(preference)},
        )
        self.assertEqual(len(rule.evidence_event_ids), 2)

    def test_an_emerging_preference_cannot_back_a_rule(self):
        preference = self.reinforce(self.make_event(dedupe_key='solo'))
        with self.assertRaises(LearningError):
            promote_preference_to_rule(preference=preference)

    def test_a_replayed_event_cannot_unlock_promotion(self):
        """Reinforcing with one event three times leaves the preference
        EMERGING, so there is nothing a learned rule could rest on."""
        event = self.make_event(dedupe_key='only-one')
        for _ in range(3):
            preference = self.reinforce(event)

        self.assertEqual(preference.evidence_count, 1)
        with self.assertRaises(LearningError):
            promote_preference_to_rule(preference=preference)
        self.assertFalse(BrandRule.objects.exists())

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

    def test_evidence_from_another_brand_never_reaches_a_preference(self):
        preference = self.make_established_preference()
        foreign = self.make_event(brand=self.brand1b, dedupe_key='x0')
        with self.assertRaises(LearningError):
            self.reinforce(foreign)
        self.assertEqual(
            set(preference_evidence_events(preference).values_list('brand_id', flat=True)),
            {self.brand1.id},
        )

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


class ScopeConsistencyTests(LearningTestBase):
    """Scope and brand have to mean the same thing to the writer and the
    resolver, or a row belongs to nobody and is silently never resolved."""

    def test_brand_scope_requires_a_brand(self):
        for scope in (LearningScope.BRAND, LearningScope.CAMPAIGN, LearningScope.ASSET):
            with self.subTest(scope=scope):
                with self.assertRaises(LearningError):
                    self.reinforce(
                        self.make_event(dedupe_key=f'ns-{scope}'),
                        brand=None,
                        scope=scope,
                    )
                with self.assertRaises(LearningError):
                    create_explicit_rule(
                        workspace=self.workspace1, brand=None,
                        text='brandless', scope=scope,
                    )

    def test_tenant_scope_must_not_name_a_brand(self):
        with self.assertRaises(LearningError):
            self.reinforce(
                self.make_event(dedupe_key='tenant-with-brand'),
                scope=LearningScope.TENANT,
            )
        with self.assertRaises(LearningError):
            create_explicit_rule(
                workspace=self.workspace1, brand=self.brand1,
                text='tenant-with-brand', scope=LearningScope.TENANT,
            )

    def test_a_workspace_wide_preference_resolves_for_every_brand(self):
        event = record_event(
            workspace=self.workspace1, brand=None,
            event_type=LearningEvent.EventType.PREFERENCE_SIGNAL,
        )
        preference = reinforce_preference(
            workspace=self.workspace1, brand=None, event=event,
            category='TONE', attribute='register', value='plain',
            scope=LearningScope.TENANT,
        )
        for brand in (self.brand1, self.brand1b):
            with self.subTest(brand=brand.name):
                self.assertIn(
                    preference,
                    resolve_preferences(workspace=self.workspace1, brand=brand),
                )

    def test_only_one_live_workspace_wide_preference_per_attribute(self):
        event = record_event(
            workspace=self.workspace1, brand=None,
            event_type=LearningEvent.EventType.PREFERENCE_SIGNAL,
        )
        reinforce_preference(
            workspace=self.workspace1, brand=None, event=event,
            category='TONE', attribute='register', value='plain',
            scope=LearningScope.TENANT,
        )
        with self.assertRaises(IntegrityError):
            BrandPreference.objects.create(
                workspace=self.workspace1, brand=None,
                category='TONE', attribute='register', value='ornate',
                scope=LearningScope.TENANT,
            )

    def test_the_database_refuses_a_scope_brand_mismatch(self):
        with self.assertRaises(IntegrityError):
            BrandPreference.objects.create(
                workspace=self.workspace1, brand=None,
                category='TONE', attribute='register',
                scope=LearningScope.BRAND,
            )

    def test_a_brand_scoped_preference_stays_with_its_brand(self):
        preference = self.make_established_preference()
        self.assertNotIn(
            preference,
            resolve_preferences(workspace=self.workspace1, brand=self.brand1b),
        )


class PromotionEvidenceTests(LearningTestBase):
    """CTO blocker: promotion counted a caller-supplied list, so one event
    listed twice cleared a two-event threshold and a rule could cite lineage
    its preference never rested on."""

    def test_promotion_cannot_be_fed_a_list_at_all(self):
        import inspect

        signature = inspect.signature(promote_preference_to_rule)
        self.assertNotIn('evidence_events', signature.parameters)

    def test_a_rule_cites_exactly_the_preference_evidence(self):
        preference = self.make_established_preference()
        unrelated = self.make_event(dedupe_key='unrelated')
        rule = promote_preference_to_rule(preference=preference)
        self.assertNotIn(str(unrelated.pk), rule.evidence_event_ids)
        self.assertEqual(
            set(rule.evidence_event_ids),
            {str(e.pk) for e in preference_evidence_events(preference)},
        )

    def test_a_replayed_event_still_cannot_reach_promotion(self):
        event = self.make_event(dedupe_key='one-only')
        for _ in range(5):
            preference = self.reinforce(event)
        self.assertEqual(preference.evidence_count, 1)
        with self.assertRaises(LearningError):
            promote_preference_to_rule(preference=preference)
        self.assertFalse(BrandRule.objects.exists())


class EvidenceLifecycleTests(LearningTestBase):
    """CTO blocker: evidence cascaded away without the count or the state
    noticing, leaving a preference ESTABLISHED on evidence that is gone."""

    def test_losing_evidence_demotes_the_preference(self):
        preference = self.make_established_preference()
        self.assertEqual(preference.state, BrandPreference.State.ESTABLISHED)

        preference_evidence_events(preference).first().delete()

        preference.refresh_from_db()
        self.assertEqual(preference.evidence_count, 1)
        self.assertEqual(preference.state, BrandPreference.State.EMERGING)

    def test_a_demoted_preference_can_no_longer_back_a_rule(self):
        preference = self.make_established_preference()
        preference_evidence_events(preference).first().delete()
        preference.refresh_from_db()
        with self.assertRaises(LearningError):
            promote_preference_to_rule(preference=preference)

    def test_a_tenant_preference_refuses_one_brands_evidence(self):
        """It would resolve for every sibling brand on evidence only ever seen
        about one of them - and promotion would then refuse that same
        evidence, stranding the preference."""
        with self.assertRaises(LearningError):
            reinforce_preference(
                workspace=self.workspace1, brand=None,
                event=self.make_event(dedupe_key='brandy'),
                category='TONE', attribute='register',
                scope=LearningScope.TENANT,
            )
        self.assertFalse(BrandPreference.objects.exists())
