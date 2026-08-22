"""
PR4 — Brand Brain compiler.

The two properties everything else rests on: the same authoritative inputs
compile to the same bytes, and deleting the snapshot loses nothing. Most of
these tests are about the second one — proving the column is a cache, not a
source of truth.
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from itertools import count
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status

from apps.common.testing import TenantFixtureMixin, workspace_header
from apps.inspirations.models import BrandInspiration, InspirationSignal
from apps.knowledge.models import BrandMemory, BrandSource
from apps.learning.models import BrandPreference, BrandRule, LearningScope
from apps.learning.services import create_explicit_rule, record_event, reinforce_preference
from apps.workspaces.models import WorkspaceMember

from .models import Brand
from .services import brand_brain
from .services.brand_brain import (
    SCHEMA_VERSION,
    compile_brand_brain,
    rebuild_brand_brain,
)

User = get_user_model()
BRANDS_URL = '/api/marketing/brands/'
# A stamp of our own, so no assertion in this file rests on how finely the
# host clock ticks.
FIXED_TIME = datetime(2026, 1, 1, 9, 0, tzinfo=dt_timezone.utc)


class BrandBrainTestBase(TenantFixtureMixin, TestCase):
    def setUp(self):
        self.workspace1 = self.make_workspace('Workspace 1', 'c1')
        self.user1, self.client1 = self.authenticate_as(
            self.workspace1, WorkspaceMember.Role.ADMIN, 'user1'
        )
        self.brand1 = Brand.objects.create(
            workspace=self.workspace1, name='Brand 1', industry='Retail',
            tagline='Made properly', brand_tone='Dry and direct',
        )
        self.brand1b = Brand.objects.create(workspace=self.workspace1, name='Brand 1b')

        self.workspace2 = self.make_workspace('Workspace 2', 'c2')
        self.user2, self.client2 = self.authenticate_as(
            self.workspace2, WorkspaceMember.Role.ADMIN, 'user2'
        )
        self.brand2 = Brand.objects.create(workspace=self.workspace2, name='Brand 2')

    def ws1(self):
        return workspace_header(self.workspace1)

    def pinned_clock(self):
        """Hand every compile inside the block its own timestamp.

        compiled_at is the only thing separating two back-to-back compiles,
        and nothing makes the clock tick between them - on a coarse timer they
        tie and a test about the payload fails on the stopwatch.
        """
        ticks = count()
        return mock.patch.object(
            brand_brain.timezone, 'now',
            side_effect=lambda: FIXED_TIME + timedelta(minutes=next(ticks)),
        )

    # --- fixtures --------------------------------------------------------

    def add_source(self, brand=None, status_=BrandSource.SourceStatus.READY):
        return BrandSource.objects.create(
            workspace=(brand or self.brand1).workspace,
            brand=brand or self.brand1,
            title='Deck', status=status_,
        )

    def add_memory(self, content, memory_type=BrandMemory.MemoryType.PRODUCT_TRUTH,
                   brand=None, source=None, normalized_key='',
                   state=BrandMemory.MemoryStatus.CONFIRMED):
        brand = brand or self.brand1
        return BrandMemory.objects.create(
            workspace=brand.workspace, brand=brand, source=source,
            memory_type=memory_type, content=content,
            normalized_key=normalized_key, status=state,
        )

    def add_inspiration(self, brand=None):
        brand = brand or self.brand1
        return BrandInspiration.objects.create(
            workspace=brand.workspace, brand=brand, title='Reference',
            reference_url='https://example.com/x',
        )

    def add_signal(self, inspiration=None, origin=InspirationSignal.Origin.USER,
                   category='TYPOGRAPHY', attribute='headline_face',
                   value='Condensed grotesque',
                   sentiment=InspirationSignal.Sentiment.LIKED):
        return InspirationSignal.objects.create(
            inspiration=inspiration or self.add_inspiration(),
            category=category, attribute=attribute, value=value,
            sentiment=sentiment, origin=origin,
            user_confirmation=(
                InspirationSignal.UserConfirmation.CONFIRMED
                if origin == InspirationSignal.Origin.USER
                else InspirationSignal.UserConfirmation.PENDING
            ),
        )

    def add_established_preference(self, category='COLOR', attribute='accent',
                                   value='acid green', brand=None):
        brand = brand or self.brand1
        for i in range(BrandPreference.ESTABLISHED_AT_EVIDENCE):
            event = record_event(
                workspace=brand.workspace, brand=brand,
                event_type='REJECTED', dedupe_key=f'{category}-{attribute}-{i}-{brand.pk}',
            )
            preference = reinforce_preference(
                workspace=brand.workspace, brand=brand, event=event,
                category=category, attribute=attribute, value=value,
            )
        return preference


class DeterminismTests(BrandBrainTestBase):
    def test_same_inputs_compile_to_the_same_fingerprint(self):
        self.add_memory('Ships in 48 hours')
        create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1, text='No handshakes',
            hardness=BrandRule.Hardness.HARD, created_by=self.user1,
        )
        self.add_signal()

        first = compile_brand_brain(self.brand1)
        second = compile_brand_brain(self.brand1)
        self.assertEqual(first['brain_version'], second['brain_version'])

    def test_compiled_at_changes_without_changing_the_fingerprint(self):
        self.add_memory('Ships in 48 hours')
        with self.pinned_clock():
            first = compile_brand_brain(self.brand1)
            second = compile_brand_brain(self.brand1)
        self.assertNotEqual(first['compiled_at'], second['compiled_at'])
        self.assertEqual(first['brain_version'], second['brain_version'])

    def test_ordering_survives_a_different_natural_order(self):
        """The fingerprint must describe the inputs, not the order the
        database happens to hand them back in.

        The rows keep their ids - recreating them would legitimately change
        the brain, because the source ids are part of what makes it
        explainable. What must not matter is which one comes back first.

        Flipping created_at moves the model's natural order and nothing else -
        the compiler pins order_by('id') and never reads created_at - so on
        its own it proves nothing about the fingerprint. The second half is
        the one with teeth: it hands the compiler the rows back to front,
        which is the only ordering the hash can actually see.
        """
        for value in ('zeta', 'alpha', 'mu'):
            self.add_memory(f'Fact {value}')
        forward = compile_brand_brain(self.brand1)['brain_version']

        # Compared against the order that was ACTUALLY in force, not against
        # id order: `order_by('id')` on a uuid4 primary key is a random
        # permutation, so the old assertion coincided with insertion order
        # roughly one run in six and failed on its own precondition. Stamps
        # are assigned rather than reversed for the same reason - nothing
        # here should depend on what the clock did.
        natural_before = [r.pk for r in BrandMemory.objects.all()]
        for offset, pk in enumerate(natural_before):
            BrandMemory.objects.filter(pk=pk).update(
                created_at=FIXED_TIME + timedelta(minutes=offset)
            )
        self.assertNotEqual(
            [r.pk for r in BrandMemory.objects.all()],
            natural_before,
            "the natural ordering did not actually change",
        )
        self.assertEqual(forward, compile_brand_brain(self.brand1)['brain_version'])

        handed = [m.pk for m in brand_brain._memories(self.brand1)]

        def backwards(accessor):
            return lambda brand: list(accessor(brand))[::-1]

        with mock.patch.multiple(
            brand_brain,
            _memories=backwards(brand_brain._memories),
            _rules=backwards(brand_brain._rules),
            _preferences=backwards(brand_brain._preferences),
            _signals=backwards(brand_brain._signals),
        ):
            self.assertEqual(
                [m.pk for m in brand_brain._memories(self.brand1)], handed[::-1],
                "the compiler was not actually handed a different order",
            )
            self.assertEqual(
                forward, compile_brand_brain(self.brand1)['brain_version']
            )

    def test_a_content_change_changes_the_fingerprint(self):
        """Positive control: the hash is not constant."""
        before = compile_brand_brain(self.brand1)['brain_version']
        self.add_memory('Ships in 48 hours')
        self.assertNotEqual(before, compile_brand_brain(self.brand1)['brain_version'])


class RebuildTests(BrandBrainTestBase):
    def test_deleting_the_snapshot_loses_nothing(self):
        self.add_memory('Ships in 48 hours')
        self.add_signal()
        original = rebuild_brand_brain(self.brand1)

        self.brand1.creative_brain = {}
        self.brand1.save(update_fields=['creative_brain'])
        self.brand1.refresh_from_db()
        self.assertEqual(self.brand1.creative_brain, {})

        rebuilt = rebuild_brand_brain(self.brand1)
        self.assertEqual(rebuilt['brain_version'], original['brain_version'])
        self.assertEqual(
            rebuilt['verified_product_truth'], original['verified_product_truth']
        )

    def test_a_corrupted_snapshot_is_reconstructed(self):
        self.add_memory('Ships in 48 hours')
        good = rebuild_brand_brain(self.brand1)

        self.brand1.creative_brain = {'garbage': True, 'brain_version': 'nonsense'}
        self.brand1.save(update_fields=['creative_brain'])

        self.brand1.refresh_from_db()
        rebuilt = rebuild_brand_brain(self.brand1)
        self.assertEqual(rebuilt['brain_version'], good['brain_version'])

    def test_source_records_are_untouched_by_compilation(self):
        memory = self.add_memory('Ships in 48 hours')
        rule = create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1, text='No handshakes',
        )
        signal = self.add_signal()
        preference = self.add_established_preference()
        before = [
            (memory.content, memory.status),
            (rule.text, rule.is_active, rule.origin),
            (signal.value, signal.origin, signal.user_confirmation),
            (preference.state, preference.evidence_count),
        ]

        rebuild_brand_brain(self.brand1)

        memory.refresh_from_db(); rule.refresh_from_db()
        signal.refresh_from_db(); preference.refresh_from_db()
        self.assertEqual(before, [
            (memory.content, memory.status),
            (rule.text, rule.is_active, rule.origin),
            (signal.value, signal.origin, signal.user_confirmation),
            (preference.state, preference.evidence_count),
        ])

    def test_the_schema_is_complete_and_provider_neutral(self):
        brain = compile_brand_brain(self.brand1)
        for key in (
            'schema_version', 'brain_version', 'compiled_at', 'identity',
            'positioning', 'audiences', 'voice', 'visual_language',
            'verified_product_truth', 'hard_rules', 'soft_rules', 'preferences',
            'inspiration_signals', 'win_patterns', 'avoid_patterns',
            'unresolved_conflict_count', 'sources',
        ):
            with self.subTest(key=key):
                self.assertIn(key, brain)
        self.assertEqual(brain['schema_version'], SCHEMA_VERSION)

    def test_no_provider_specific_configuration_leaks_in(self):
        import json

        self.add_memory('Ships in 48 hours')
        create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1, text='No handshakes',
        )
        self.add_signal()
        blob = json.dumps(compile_brand_brain(self.brand1)).lower()
        for token in (
            'gemini', 'openai', 'gpt', 'claude', 'anthropic', 'api_key',
            'model_name', 'temperature', 'prompt', 'system_message',
        ):
            with self.subTest(token=token):
                self.assertNotIn(token, blob)


class PrecedenceTests(BrandBrainTestBase):
    def test_a_hard_explicit_rule_outranks_a_learned_soft_rule(self):
        create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1,
            text='Always use the wordmark',
            hardness=BrandRule.Hardness.HARD,
            structured={'category': 'BRANDING', 'attribute': 'logo', 'value': 'wordmark'},
        )
        BrandRule.objects.create(
            workspace=self.workspace1, brand=self.brand1,
            text='Prefer the icon', hardness=BrandRule.Hardness.SOFT,
            origin=BrandRule.Origin.LEARNED,
            structured={'category': 'BRANDING', 'attribute': 'logo', 'value': 'icon'},
        )

        brain = compile_brand_brain(self.brand1)
        logo = [c for c in brain['preferences'] if c['attribute'] == 'logo']
        self.assertEqual(len(logo), 1)
        self.assertEqual(logo[0]['value'], 'wordmark')
        self.assertEqual(logo[0]['authority'], 'hard_explicit_rule')
        self.assertEqual(brain['unresolved_conflict_count'], 0)
        self.assertIn('icon', [o['value'] for o in brain['overridden']])

    def test_an_explicit_human_preference_outranks_an_inference(self):
        inspiration = self.add_inspiration()
        self.add_signal(
            inspiration=inspiration, origin=InspirationSignal.Origin.USER,
            value='Condensed grotesque',
        )
        # An AI signal on a DIFFERENT attribute, so PR2's conflict rule does
        # not simply suppress it - the brain's own precedence must do the work.
        other = self.add_inspiration()
        InspirationSignal.objects.create(
            inspiration=other, category='TYPOGRAPHY', attribute='headline_face',
            value='Serif display', sentiment=InspirationSignal.Sentiment.LIKED,
            origin=InspirationSignal.Origin.AI,
            user_confirmation=InspirationSignal.UserConfirmation.PENDING,
        )

        brain = compile_brand_brain(self.brand1)
        face = [c for c in brain['preferences'] if c['attribute'] == 'headline_face']
        self.assertEqual(len(face), 1)
        self.assertEqual(face[0]['value'], 'Condensed grotesque')
        self.assertEqual(face[0]['authority'], 'explicit_preference')

    def test_an_established_preference_outranks_an_emerging_one(self):
        self.add_established_preference(category='COLOR', attribute='accent',
                                        value='acid green')
        BrandPreference.objects.create(
            workspace=self.workspace1, brand=self.brand1b,
            category='COLOR', attribute='accent', value='navy',
        )
        brain = compile_brand_brain(self.brand1)
        accent = [c for c in brain['preferences'] if c['attribute'] == 'accent']
        self.assertEqual(accent[0]['value'], 'acid green')
        self.assertEqual(accent[0]['authority'], 'established_preference')

    def test_an_unresolved_conflict_is_surfaced_not_collapsed(self):
        """Two HARD explicit rules disagreeing: nothing outranks anything, so
        the brain says so rather than picking."""
        for value in ('wordmark', 'icon'):
            create_explicit_rule(
                workspace=self.workspace1, brand=self.brand1,
                text=f'Always use the {value}', hardness=BrandRule.Hardness.HARD,
                structured={'category': 'BRANDING', 'attribute': 'logo', 'value': value},
            )

        brain = compile_brand_brain(self.brand1)
        self.assertEqual(brain['unresolved_conflict_count'], 1)
        conflict = brain['conflicts'][0]
        self.assertEqual(conflict['attribute'], 'logo')
        self.assertEqual(conflict['reason'], 'EQUAL_AUTHORITY_DISAGREEMENT')
        self.assertEqual(len(conflict['claims']), 2)
        # And nothing about that attribute is asserted as the brand's position.
        self.assertEqual(
            [c for c in brain['preferences'] if c['attribute'] == 'logo'], []
        )

    def test_conflicting_confirmed_memories_do_not_become_product_truth(self):
        self.add_memory('Ships in 48 hours', normalized_key='shipping_time')
        self.add_memory('Ships in 5 days', normalized_key='shipping_time')

        brain = compile_brand_brain(self.brand1)
        self.assertEqual(brain['unresolved_conflict_count'], 1)
        self.assertEqual(brain['verified_product_truth'], [])

    def test_win_and_avoid_patterns_come_from_sentiment(self):
        self.add_signal(value='Generous white space',
                        sentiment=InspirationSignal.Sentiment.LIKED)
        self.add_signal(
            inspiration=self.add_inspiration(), attribute='stock_photography',
            category='IMAGERY', value='Handshake stock',
            sentiment=InspirationSignal.Sentiment.DISLIKED,
        )
        brain = compile_brand_brain(self.brand1)
        self.assertIn('Generous white space', brain['win_patterns'])
        self.assertIn('Handshake stock', brain['avoid_patterns'])


class EligibilityTests(BrandBrainTestBase):
    def test_knowledge_from_an_archived_source_is_excluded(self):
        source = self.add_source()
        self.add_memory('Ships in 48 hours', source=source)
        self.assertIn('Ships in 48 hours',
                      compile_brand_brain(self.brand1)['verified_product_truth'])

        source.status = BrandSource.SourceStatus.ARCHIVED
        source.save(update_fields=['status'])

        brain = compile_brand_brain(self.brand1)
        self.assertNotIn('Ships in 48 hours', brain['verified_product_truth'])
        # ...and the memory row itself is still there for audit.
        self.assertTrue(BrandMemory.objects.filter(content='Ships in 48 hours').exists())

    def test_memory_without_a_source_is_not_dropped(self):
        """The archived-source exclusion must not take source-less rows with it."""
        self.add_memory('Founded in a shed', source=None)
        self.assertIn('Founded in a shed',
                      compile_brand_brain(self.brand1)['verified_product_truth'])

    def test_an_unconfirmed_memory_is_excluded(self):
        self.add_memory('Rumoured', state=BrandMemory.MemoryStatus.CANDIDATE)
        self.assertEqual(compile_brand_brain(self.brand1)['verified_product_truth'], [])

    def test_a_superseded_inspiration_signal_is_excluded(self):
        first = self.add_signal(value='Condensed grotesque')
        brain = compile_brand_brain(self.brand1)
        self.assertIn(str(first.pk), brain['sources']['inspiration_signal_ids'])

        from django.utils import timezone

        from apps.inspirations.models import SupersessionReason

        first.superseded_at = timezone.now()
        first.superseded_reason = SupersessionReason.NEWER_USER_SIGNAL
        first.save(update_fields=['superseded_at', 'superseded_reason'])

        brain = compile_brand_brain(self.brand1)
        self.assertNotIn(str(first.pk), brain['sources']['inspiration_signal_ids'])

    def test_a_retired_learning_preference_is_excluded(self):
        preference = self.add_established_preference()
        self.assertIn(str(preference.pk),
                      compile_brand_brain(self.brand1)['sources']['preference_ids'])

        preference.state = BrandPreference.State.RETIRED
        preference.save(update_fields=['state'])

        self.assertNotIn(str(preference.pk),
                         compile_brand_brain(self.brand1)['sources']['preference_ids'])

    def test_an_inactive_rule_is_excluded(self):
        rule = create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1, text='No handshakes',
            hardness=BrandRule.Hardness.HARD,
        )
        self.assertEqual(len(compile_brand_brain(self.brand1)['hard_rules']), 1)

        rule.is_active = False
        rule.save(update_fields=['is_active'])

        self.assertEqual(compile_brand_brain(self.brand1)['hard_rules'], [])


class BrainIsolationTests(BrandBrainTestBase):
    def test_another_tenants_records_never_enter_this_brain(self):
        self.add_memory('Their secret', brand=self.brand2)
        create_explicit_rule(
            workspace=self.workspace2, brand=self.brand2, text='Their rule',
            hardness=BrandRule.Hardness.HARD,
        )
        self.add_signal(inspiration=self.add_inspiration(brand=self.brand2),
                        value='Their typeface')
        self.add_established_preference(brand=self.brand2)

        brain = compile_brand_brain(self.brand1)
        self.assertEqual(brain['verified_product_truth'], [])
        self.assertEqual(brain['hard_rules'], [])
        self.assertEqual(brain['sources']['inspiration_signal_ids'], [])
        self.assertEqual(brain['sources']['preference_ids'], [])

    def test_a_sibling_brands_records_never_enter_this_brain(self):
        self.add_memory('Sibling fact', brand=self.brand1b)
        create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1b, text='Sibling rule',
            hardness=BrandRule.Hardness.HARD,
        )
        self.add_signal(inspiration=self.add_inspiration(brand=self.brand1b),
                        value='Sibling typeface')

        brain = compile_brand_brain(self.brand1)
        self.assertEqual(brain['verified_product_truth'], [])
        self.assertEqual(brain['hard_rules'], [])
        self.assertEqual(brain['sources']['inspiration_signal_ids'], [])

    def test_a_workspace_wide_rule_does_reach_every_brand(self):
        """Positive control for the isolation tests above."""
        create_explicit_rule(
            workspace=self.workspace1, brand=None, text='Workspace-wide',
            hardness=BrandRule.Hardness.HARD, scope=LearningScope.TENANT,
        )
        for brand in (self.brand1, self.brand1b):
            with self.subTest(brand=brand.name):
                self.assertEqual(len(compile_brand_brain(brand)['hard_rules']), 1)


class BrainEndpointTests(BrandBrainTestBase):
    def test_rebuild_endpoint_persists_the_snapshot(self):
        self.add_memory('Ships in 48 hours')
        response = self.client1.post(
            f'{BRANDS_URL}{self.brand1.id}/rebuild-brain/', format='json', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.brand1.refresh_from_db()
        self.assertEqual(
            self.brand1.creative_brain['brain_version'],
            response.json()['data']['brain_version'],
        )

    def test_another_tenant_cannot_rebuild_this_brain(self):
        response = self.client2.post(
            f'{BRANDS_URL}{self.brand1.id}/rebuild-brain/',
            format='json', **workspace_header(self.workspace2),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_a_viewer_cannot_rebuild(self):
        _, viewer_client = self.authenticate_as(
            self.workspace1, WorkspaceMember.Role.VIEWER, 'viewer'
        )
        response = viewer_client.post(
            f'{BRANDS_URL}{self.brand1.id}/rebuild-brain/', format='json', **self.ws1()
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_reading_a_never_compiled_brain_compiles_it_rather_than_lying(self):
        self.add_memory('Ships in 48 hours')
        self.assertEqual(self.brand1.creative_brain, {})
        body = self.client1.get(
            f'{BRANDS_URL}{self.brand1.id}/brain/', **self.ws1()
        ).json()['data']
        self.assertIn('Ships in 48 hours', body['verified_product_truth'])


class VerifiedFactPrecedenceTests(BrandBrainTestBase):
    """A confirmed memory with a `normalized_key` is asserting something about
    a named thing, so it competes with rules, preferences and inferences
    instead of sitting in a list where a softer claim about the same key could
    quietly become the answer."""

    KEY = 'FACT/roast_freshness'

    def add_keyed_fact(self, content='Roasted within 48 hours of shipping', source=None):
        return self.add_memory(content, normalized_key=self.KEY, source=source)

    def contradicting_signal(self, value='Roasted within 7 days'):
        return self.add_signal(
            category='FACT', attribute='roast_freshness', value=value,
            origin=InspirationSignal.Origin.USER,
            sentiment=InspirationSignal.Sentiment.NEUTRAL,
        )

    def test_a_verified_fact_outranks_an_explicit_human_preference(self):
        fact = self.add_keyed_fact()
        signal = self.contradicting_signal()

        brain = compile_brand_brain(self.brand1)
        claim = {c['attribute']: c for c in brain['preferences']}['roast_freshness']
        self.assertEqual(claim['value'], fact.content)
        self.assertEqual(claim['authority'], 'verified_fact')
        self.assertEqual(brain['unresolved_conflict_count'], 0)

        outranked = [o for o in brain['overridden'] if o['source_id'] == str(signal.pk)]
        self.assertEqual(len(outranked), 1)
        self.assertEqual(outranked[0]['authority'], 'explicit_preference')

    def test_a_verified_fact_outranks_a_learned_rule(self):
        fact = self.add_keyed_fact()
        rule = BrandRule.objects.create(
            workspace=self.workspace1, brand=self.brand1,
            text='Roasted within 7 days', hardness=BrandRule.Hardness.SOFT,
            origin=BrandRule.Origin.LEARNED,
            structured={'category': 'FACT', 'attribute': 'roast_freshness',
                        'value': 'Roasted within 7 days'},
        )

        brain = compile_brand_brain(self.brand1)
        claim = {c['attribute']: c for c in brain['preferences']}['roast_freshness']
        self.assertEqual(claim['value'], fact.content)
        self.assertEqual(claim['authority'], 'verified_fact')
        self.assertIn(
            str(rule.pk), [o['source_id'] for o in brain['overridden']]
        )

    def test_a_hard_explicit_rule_still_outranks_a_verified_fact(self):
        """Positive control on the top of the hierarchy."""
        self.add_keyed_fact()
        create_explicit_rule(
            workspace=self.workspace1, brand=self.brand1,
            text='Say roasted to order', hardness=BrandRule.Hardness.HARD,
            structured={'category': 'FACT', 'attribute': 'roast_freshness',
                        'value': 'Roasted to order'},
        )
        brain = compile_brand_brain(self.brand1)
        claim = {c['attribute']: c for c in brain['preferences']}['roast_freshness']
        self.assertEqual(claim['authority'], 'hard_explicit_rule')

    def test_two_verified_facts_that_disagree_stay_an_unresolved_conflict(self):
        self.add_keyed_fact('Roasted within 48 hours of shipping')
        self.add_keyed_fact('Roasted within 5 days of shipping')

        brain = compile_brand_brain(self.brand1)
        self.assertEqual(brain['unresolved_conflict_count'], 1)
        conflict = brain['conflicts'][0]
        self.assertEqual(conflict['authority'], 'verified_fact')
        self.assertEqual(len(conflict['claims']), 2)
        # Neither is asserted, and neither reaches product truth.
        self.assertEqual(
            [c for c in brain['preferences'] if c['attribute'] == 'roast_freshness'], []
        )
        self.assertEqual(brain['verified_product_truth'], [])

    def test_a_lower_claim_does_not_win_when_the_facts_cancel_out(self):
        self.add_keyed_fact('Roasted within 48 hours of shipping')
        self.add_keyed_fact('Roasted within 5 days of shipping')
        signal = self.contradicting_signal()

        brain = compile_brand_brain(self.brand1)
        self.assertEqual(
            [c for c in brain['preferences'] if c['attribute'] == 'roast_freshness'], []
        )
        self.assertIn(str(signal.pk), [o['source_id'] for o in brain['overridden']])

    def test_unkeyed_memories_are_untouched_by_any_of_this(self):
        """Narrative memory keeps its semantic home and is never forced into
        an invented claim key."""
        self.add_memory('We started in a shed',
                        memory_type=BrandMemory.MemoryType.POSITIONING_SIGNAL)
        self.add_memory('Beginners find grinding intimidating',
                        memory_type=BrandMemory.MemoryType.BUYER_PAIN)
        self.add_keyed_fact('Roasted within 48 hours of shipping')
        self.add_keyed_fact('Roasted within 5 days of shipping')

        brain = compile_brand_brain(self.brand1)
        self.assertIn('We started in a shed', brain['positioning']['statements'])
        self.assertIn('Beginners find grinding intimidating', brain['audiences']['pains'])
        # The unrelated conflict did not drag them in.
        self.assertEqual(
            [c['attribute'] for c in brain['preferences']], []
        )

    def test_a_fact_from_an_archived_source_stops_outranking_anything(self):
        source = self.add_source()
        self.add_keyed_fact(source=source)
        signal = self.contradicting_signal()
        self.assertEqual(
            {c['attribute']: c for c in
             compile_brand_brain(self.brand1)['preferences']}['roast_freshness'
             ]['authority'],
            'verified_fact',
        )

        source.status = BrandSource.SourceStatus.ARCHIVED
        source.save(update_fields=['status'])

        brain = compile_brand_brain(self.brand1)
        claim = {c['attribute']: c for c in brain['preferences']}['roast_freshness']
        self.assertEqual(claim['source_id'], str(signal.pk))
        self.assertEqual(claim['authority'], 'explicit_preference')

    def test_keyed_facts_keep_the_fingerprint_deterministic(self):
        self.add_keyed_fact()
        self.contradicting_signal()
        with self.pinned_clock():
            first = compile_brand_brain(self.brand1)
            second = compile_brand_brain(self.brand1)
        self.assertEqual(first['brain_version'], second['brain_version'])
        self.assertNotEqual(first['compiled_at'], second['compiled_at'])
